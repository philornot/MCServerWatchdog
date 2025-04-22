import base64
import datetime
import hashlib
import io
import os
import pickle
import shutil

import aiohttp
import discord
import pytz
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from pretty_logger import PrettyLogger

# Załaduj zmienne środowiskowe z pliku .env
load_dotenv()

# Konfiguracja
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # ID kanału, gdzie bot będzie wysyłał wiadomości
MC_SERVER_ADDRESS = os.getenv("MC_SERVER_ADDRESS")  # Adres serwera MC (IP lub domena)
MC_SERVER_PORT = int(os.getenv("MC_SERVER_PORT", "25565"))  # Domyślny port MC to 25565
COMMAND_COOLDOWN = 30  # Czas odnowienia w sekundach
LOG_FILE = os.getenv("LOG_FILE", "logs/mcserverwatch.log")  # Ścieżka do pliku logów
DATA_FILE = os.getenv("DATA_FILE", "data/bot_data.pickle")  # Plik do zapisywania danych bota
GUILD_ID = os.getenv("GUILD_ID")  # ID serwera Discord, opcjonalnie dla szybszego rozwoju komend
# Konfiguracja związana z ikonami
ENABLE_SERVER_ICONS = os.getenv("ENABLE_SERVER_ICONS", "true").lower() == "true"  # Włącz/wyłącz obsługę ikon
SAVE_SERVER_ICONS = os.getenv("SAVE_SERVER_ICONS", "true").lower() == "true"  # Czy zapisywać ikony lokalnie
SERVER_ICONS_DIR = os.getenv("SERVER_ICONS_DIR", "data/icons")  # Katalog do zapisywania ikon
MAX_ICON_SIZE_KB = int(os.getenv("MAX_ICON_SIZE_KB", "256"))  # Maksymalny rozmiar ikony w KB

# Inicjalizacja loggera
logger = PrettyLogger(
    log_file=LOG_FILE,
    console_level="INFO",
    file_level="DEBUG",
    max_json_length=300,  # Maksymalna długość JSON-ów w logach
    trim_lists=True,  # Przycinaj długie listy
    verbose_api=False  # Nie loguj pełnych odpowiedzi API
)

# Słownik do przechowywania informacji o ostatniej aktywności graczy
last_seen = {}

last_command_usage = {}

# Zapamiętana maksymalna liczba graczy na serwerze
max_players = 20

# Czas ostatniego znanego stanu online serwera
last_known_online_time = None

# Inicjalizacja bota
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)  # Command tree dla komend slash

# ID ostatnio wysłanego embeda
last_embed_id = None

# Format czasu warszawskiego
warsaw_tz = pytz.timezone('Europe/Warsaw')


def get_bot_version():
    """
    Odczytuje wersję bota z pliku version.txt lub zwraca wersję developerską.

    Jeśli plik version.txt istnieje (generowany przez GitHub Actions),
    funkcja odczytuje wersję z pliku. W przeciwnym razie zwraca
    informację, że jest to wersja developerska.

    Returns:
        str: Wersja bota
    """
    try:
        if os.path.exists("version.txt"):
            with open("version.txt", "r") as f:
                return f.read().strip()
        return "dev-local"
    except Exception as ex:
        logger.warning("Version", f"Nie udało się odczytać wersji: {ex}", log_type="CONFIG")
        return "unknown"


# Zmienna globalna przechowująca wersję
BOT_VERSION = get_bot_version()
logger.info("Version", f"Uruchamianie bota w wersji: {BOT_VERSION}", log_type="CONFIG")


def ensure_data_dir():
    """
    Upewnia się, że katalog danych istnieje.

    Funkcja tworzy katalog dla plików danych, jeśli nie istnieje.
    Jest wywoływana przed zapisem danych, aby uniknąć błędów FileNotFoundError.
    """
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)


def save_bot_data():
    """
    Zapisuje dane bota do pliku.

    Funkcja serializuje dane bota (ID ostatniego embeda, informacje o ostatnio widzianych graczach,
    maksymalna liczba graczy) i zapisuje je do pliku przy użyciu modułu pickle.
    """
    ensure_data_dir()
    data = {
        "last_embed_id": last_embed_id,
        "last_seen": last_seen,
        "max_players": max_players,
        "last_known_online_time": last_known_online_time,
        "last_icon_update_time": datetime.datetime.now(warsaw_tz).timestamp()  # Dodaj czas ostatniej aktualizacji ikony
    }
    try:
        with open(DATA_FILE, "wb") as f:
            pickle.dump(data, f)
        logger.debug("DataStorage", f"Zapisano dane bota do {DATA_FILE}", log_type="CONFIG")
    except Exception as ex:
        logger.error("DataStorage", f"Błąd podczas zapisywania danych: {ex}", log_type="CONFIG")


def load_bot_data():
    """
    Ładuje dane bota z pliku.

    Funkcja wczytuje zapisane wcześniej dane bota z pliku.
    Jeśli plik nie istnieje lub wystąpi błąd, dane pozostają niezmienione.
    """
    global last_embed_id, last_seen, max_players, last_known_online_time
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "rb") as f:
                data = pickle.load(f)
                last_embed_id = data.get("last_embed_id")
                stored_last_seen = data.get("last_seen", {})
                if stored_last_seen:
                    last_seen = stored_last_seen

                # Wczytaj zapamiętaną maksymalną liczbę graczy
                stored_max_players = data.get("max_players")
                if stored_max_players:
                    max_players = stored_max_players

                # Wczytaj czas ostatniego stanu online
                stored_last_known_online_time = data.get("last_known_online_time")
                if stored_last_known_online_time:
                    last_known_online_time = stored_last_known_online_time

                logger.debug("DataStorage", f"Załadowano dane bota z {DATA_FILE}",
                             last_embed_id=last_embed_id,
                             players_count=len(last_seen),
                             max_players=max_players,
                             last_online=format_time(last_known_online_time) if last_known_online_time else "brak",
                             log_type="CONFIG")
        else:
            logger.debug("DataStorage", f"Nie znaleziono pliku danych {DATA_FILE}", log_type="CONFIG")
    except Exception as ex:
        logger.error("DataStorage", f"Błąd podczas ładowania danych: {ex}", log_type="CONFIG")


def get_warsaw_time():
    """
    Zwraca aktualny czas w strefie czasowej Warszawy.

    Returns:
        datetime: Obiekt datetime z aktualnym czasem w strefie czasowej Warszawy
    """
    return datetime.datetime.now(warsaw_tz)


def format_time(dt):
    """
    Formatuje datę i czas w czytelny sposób.

    Args:
        dt (datetime): Obiekt daty i czasu do sformatowania

    Returns:
        str: Sformatowany string z datą i czasem w formacie "HH:MM:SS DD-MM-RRRR"
    """
    return dt.strftime("%H:%M:%S %d-%m-%Y")


async def check_minecraft_server():
    """
    Sprawdza status serwera Minecraft i zwraca dane w formie słownika.

    Funkcja łączy się z API mcsrvstat.us, aby pobrać informacje o stanie serwera.
    Implementuje zaawansowane metody analizy stanu serwera, uwzględniając:
    - Dane z API (status online, MOTD, wersja, liczba graczy)
    - Historyczne dane o aktywności graczy
    - Błędy zwracane przez API
    - Czas od ostatniej znanej aktywności

    Zapewnia stabilną i wiarygodną detekcję stanu serwera, nawet jeśli API
    zwraca niepełne lub niespójne dane.

    Returns:
        dict: Słownik zawierający przetworzone informacje o serwerze i jego statusie
    """
    global max_players, last_known_online_time, last_seen

    current_time = get_warsaw_time()
    api_url = f"https://api.mcsrvstat.us/2/{MC_SERVER_ADDRESS}:{MC_SERVER_PORT}"

    try:
        logger.debug("ServerCheck", f"Sprawdzanie stanu serwera {MC_SERVER_ADDRESS}:{MC_SERVER_PORT}", log_type="API")

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.api_request(api_url, response=data, status=response.status)

                    # ===== FAZA 1: Zbieranie wskaźników stanu =====

                    # Podstawowy status z API
                    reported_online = data.get("online", False)

                    # Analiza wiadomości MOTD - ULEPSZONA DETEKCJA
                    motd_indicates_offline = False
                    motd_text = ""
                    if "motd" in data and "clean" in data["motd"] and data["motd"]["clean"]:
                        motd_text = " ".join(data["motd"]["clean"]).lower()
                        motd_indicates_offline = any(
                            keyword in motd_text for keyword in ["offline", "wyłączony", "niedostępny", "unavailable"])
                        logger.debug("ServerCheck", f"Analiza MOTD: '{motd_text}'",
                                     offline_detected=motd_indicates_offline, log_type="API")

                    # Analiza wersji - ULEPSZONA DETEKCJA
                    version_indicates_offline = False
                    version_text = ""
                    if "version" in data:
                        version_text = data.get("version", "").lower()
                        # Sprawdzamy, czy wersja zawiera słowo "offline", niezależnie od użytego symbolu
                        version_indicates_offline = "offline" in version_text
                        logger.debug("ServerCheck", f"Analiza wersji: '{version_text}'",
                                     offline_detected=version_indicates_offline, log_type="API")

                    # PRIORYTETOWA WERYFIKACJA STANU OFFLINE,
                    # Jeśli zarówno MOTD, jak i wersja wskazują na offline, serwer jest na pewno offline
                    if motd_indicates_offline and version_indicates_offline:
                        logger.debug("ServerCheck",
                                     "Wykryto jednoznacznie stan OFFLINE na podstawie MOTD i wersji",
                                     log_type="API",
                                     motd=motd_text,
                                     version=version_text)
                        data["online"] = False
                        data["error"] = "Serwer jest offline według MOTD i wersji"
                        logger.server_status(False, data)
                        return data

                    # Zapisz maksymalną liczbę graczy, jeśli dostępna
                    if "players" in data and "max" in data["players"] and data["players"]["max"] > 0:
                        max_players = data["players"]["max"]
                        logger.debug("ServerCheck", f"Zaktualizowano maksymalną liczbę graczy: {max_players}",
                                     log_type="DATA")

                    # Sprawdź błędy w odpowiedzi API
                    api_errors = []
                    if "debug" in data and "error" in data["debug"]:
                        error_data = data["debug"]["error"]
                        if isinstance(error_data, dict):
                            api_errors = list(error_data.values())
                        elif isinstance(error_data, str):
                            api_errors = [error_data]

                    # Wykryj graczy online według API
                    api_players = []
                    api_player_count = 0
                    if reported_online and "players" in data:
                        if "list" in data["players"]:
                            api_players = data["players"]["list"]
                        api_player_count = data["players"].get("online", len(api_players))

                    # ===== FAZA 2: Analiza historycznych danych =====

                    # Sprawdź, kiedy ostatnio widziano graczy
                    recent_player_activity = False
                    active_players = []
                    most_recent_time = None

                    for player, player_time in last_seen.items():
                        time_diff = (current_time - player_time).total_seconds() / 60

                        # Gracze widziani w ciągu ostatnich 5 minut są uznawani za aktywnych
                        if time_diff < 5:
                            recent_player_activity = True
                            active_players.append(player)

                            if most_recent_time is None or player_time > most_recent_time:
                                most_recent_time = player_time

                    # Status ostatniej znanej aktywności online
                    recent_server_activity = False
                    if last_known_online_time:
                        server_time_diff = (current_time - last_known_online_time).total_seconds() / 60
                        if server_time_diff < 5:
                            recent_server_activity = True

                    # ===== FAZA 3: Inteligentne ustalenie statusu =====

                    # Domyślnie przyjmujemy status z API
                    actual_online = reported_online

                    # Wskaźniki negatywne — sugerują, że serwer jest offline
                    # ZWIĘKSZONA WAGA dla wskaźników z MOTD i wersji
                    negative_indicators = [
                        not reported_online,
                        motd_indicates_offline,  # Liczony raz
                        motd_indicates_offline,  # Liczony drugi raz dla zwiększenia wagi
                        version_indicates_offline,  # Liczony raz
                        version_indicates_offline,  # Liczony drugi raz dla zwiększenia wagi
                        len(api_errors) > 0,
                    ]

                    # Wskaźniki pozytywne - sugerują, że serwer jest online
                    positive_indicators = [
                        reported_online,
                        api_player_count > 0,
                        recent_player_activity,
                        recent_server_activity
                    ]

                    # Liczba wskaźników
                    negative_count = sum(1 for ind in negative_indicators if ind)
                    positive_count = sum(1 for ind in positive_indicators if ind)

                    # Logika decyzyjna - bazuje na przewadze wskaźników
                    if positive_count > negative_count:
                        # Przewaga wskaźników pozytywnych - serwer jest online
                        actual_online = True
                        logger.debug("ServerCheck",
                                     f"Wymuszam status ONLINE na podstawie analizy wskaźników (pozytywne: {positive_count}, negatywne: {negative_count})",
                                     log_type="API",
                                     positive=positive_indicators,
                                     negative=negative_indicators)
                    elif negative_count > positive_count:
                        # Przewaga wskaźników negatywnych - serwer jest offline
                        actual_online = False
                        logger.debug("ServerCheck",
                                     f"Wymuszam status OFFLINE na podstawie analizy wskaźników (pozytywne: {positive_count}, negatywne: {negative_count})",
                                     log_type="API",
                                     positive=positive_indicators,
                                     negative=negative_indicators)
                    elif api_player_count > 0:
                        # Remis, ale API pokazuje graczy - uznajemy za online
                        actual_online = True
                        logger.debug("ServerCheck",
                                     "Remis wskaźników, ale API pokazuje graczy - uznajemy za ONLINE",
                                     log_type="API")
                    elif recent_player_activity:
                        # Remis, brak graczy w API, ale były niedawne aktywności graczy
                        actual_online = True
                        logger.debug("ServerCheck",
                                     "Remis wskaźników, ale były niedawne aktywności graczy - uznajemy za ONLINE",
                                     log_type="API",
                                     active_players=active_players)
                    else:
                        # W przypadku remisu i braku graczy - zakładamy offline
                        actual_online = False
                        logger.debug("ServerCheck",
                                     "Remis wskaźników, brak graczy - uznajemy za OFFLINE",
                                     log_type="API")

                    # ===== FAZA 4: Aktualizacja statusu i danych =====

                    # Aktualizacja statusu online w danych
                    data["online"] = actual_online

                    # Jeśli serwer faktycznie jest online, aktualizuj czas ostatniej aktywności
                    if actual_online:
                        last_known_online_time = current_time

                        # Jeśli API nie zwróciło danych o graczach, ale wiemy o aktywnych graczach, dodaj ich
                        if "players" not in data:
                            data["players"] = {}

                        if ("list" not in data["players"] or not data["players"]["list"]) and active_players:
                            data["players"]["list"] = active_players
                            data["players"]["online"] = len(active_players)
                            data["players"]["max"] = max_players
                            logger.debug("ServerCheck",
                                         f"Dodano {len(active_players)} aktywnych graczy na podstawie historii",
                                         log_type="DATA",
                                         players=active_players)

                    # Logowanie szczegółowych informacji o serwerze
                    if actual_online:
                        logger.server_status(True, data)
                    else:
                        logger.server_status(False, data)

                    return data
                else:
                    # Obsługa błędów HTTP
                    error_msg = f"Błąd API: {response.status}"
                    if response.status == 429:
                        error_msg = "Zbyt wiele zapytań do API (kod 429). Proszę spróbować ponownie za chwilę."
                    elif response.status == 404:
                        error_msg = "Serwer nie został znaleziony przez API (kod 404). Sprawdź adres i port."
                    elif response.status >= 500:
                        error_msg = f"Błąd serwera API (kod {response.status}). Spróbuj ponownie później."

                    logger.api_request(api_url, status=response.status, error=error_msg)

                    # Próba inteligentnego ustalenia statusu mimo błędu API
                    if last_known_online_time:
                        server_time_diff = (current_time - last_known_online_time).total_seconds() / 60
                        if server_time_diff < 5:
                            # Znajdź aktywnych graczy (tych widzianych w ciągu ostatnich 5 minut)
                            active_players = []
                            for player, player_time in last_seen.items():
                                if (current_time - player_time).total_seconds() / 60 < 5:
                                    active_players.append(player)

                            # Serwer był niedawno online, uznajemy, że nadal działa
                            logger.debug("ServerCheck",
                                         "Błąd API, ale serwer był niedawno online - zwracamy status ONLINE",
                                         log_type="API")
                            return {
                                "online": True,
                                "api_error": error_msg,
                                "players": {
                                    "online": len(active_players),
                                    "max": max_players,
                                    "list": active_players
                                },
                                "hostname": MC_SERVER_ADDRESS
                            }

                    # Jeśli doszliśmy tutaj, nie mamy wystarczających danych, by uznać serwer za online
                    return {"online": False, "error": error_msg}

    except Exception as ex:
        # Obsługa innych wyjątków
        error_msg = f"Wyjątek: {str(ex)}"
        logger.api_request(api_url, error=error_msg)

        # Próba zwrócenia sensownych danych mimo wyjątku
        if last_known_online_time:
            server_time_diff = (current_time - last_known_online_time).total_seconds() / 60
            if server_time_diff < 5:
                # Używamy ostatnich znanych danych
                active_players = [player for player, player_time in last_seen.items()
                                  if (current_time - player_time).total_seconds() / 60 < 5]

                return {
                    "online": True,
                    "exception": error_msg,
                    "players": {
                        "online": len(active_players),
                        "max": max_players,
                        "list": active_players
                    },
                    "hostname": MC_SERVER_ADDRESS
                }

        return {"online": False, "error": error_msg}


async def process_server_icon(server_data):
    """
    Przetwarza ikonę serwera Minecraft z danych API.

    Funkcja szczegółowo analizuje dane ikony, wykonuje niezbędne konwersje i weryfikacje,
    a następnie zwraca przygotowany obiekt ikony.
    Gdy serwer jest offline, próbuje odzyskać ostatnio zapisaną ikonę.

    Args:
        server_data (dict): Dane serwera zawierające potencjalnie pole 'icon'

    Returns:
        tuple: (bytes, str, str) - Dane binarne ikony, jej format i hash lub (None, None, None) w przypadku błędu
    """
    try:
        # Sprawdź, czy serwer jest online i czy ma ikonę
        if not server_data.get("online", False):
            logger.debug("ServerIcon", "Serwer jest offline, próbuję odzyskać ostatnio zapisaną ikonę", log_type="DATA")

            # Spróbuj odzyskać ostatnio zapisaną ikonę
            return await recover_saved_icon(MC_SERVER_ADDRESS)

        if "icon" not in server_data:
            logger.debug("ServerIcon", "Brak ikony w danych serwera", log_type="DATA")
            return None, None, None

        # Logowanie informacji początkowych
        icon_data = server_data["icon"]
        icon_length = len(icon_data) if icon_data else 0
        logger.debug("ServerIcon", f"Rozpoczynam przetwarzanie ikony serwera (długość: {icon_length})", log_type="DATA")

        # Sprawdź, czy dane ikony nie są puste
        if not icon_data:
            logger.warning("ServerIcon", "Dane ikony są puste", log_type="DATA")
            return None, None, None

        # Wykryj format danych - oczekiwany format to data URI lub czysty Base64
        icon_format = "unknown"
        try:
            if icon_data.startswith('data:image/'):
                # Dane w formacie data URI
                format_marker = icon_data.split(';')[0].replace('data:image/', '')
                icon_format = format_marker
                logger.debug("ServerIcon", f"Wykryto format ikony: {icon_format} (data URI)", log_type="DATA")

                # Wyodrębnij część Base64
                try:
                    icon_base64 = icon_data.split(',')[1]
                    logger.debug("ServerIcon", f"Wyodrębniono część Base64 (długość: {len(icon_base64)})",
                                 log_type="DATA")
                except IndexError as ex:
                    logger.error("ServerIcon", f"Błąd podczas wyodrębniania Base64 z data URI: {ex}", log_type="DATA")
                    return None, None, None
            else:
                # Zakładamy, że to czysty Base64
                icon_base64 = icon_data
                # Próbujemy wykryć format na podstawie nagłówków Base64
                if icon_base64.startswith('/9j/'):
                    icon_format = 'jpeg'
                elif icon_base64.startswith('iVBOR'):
                    icon_format = 'png'
                else:
                    icon_format = 'png'  # Domyślnie zakładamy PNG

                logger.debug("ServerIcon", f"Wykryto format ikony: {icon_format} (bezpośredni Base64)", log_type="DATA")
        except Exception as ex:
            logger.error("ServerIcon", f"Błąd podczas analizy formatu ikony: {ex}", log_type="DATA")
            return None, None, None

        # Napraw padding Base64 jeśli potrzeba
        try:
            padding_needed = 4 - (len(icon_base64) % 4) if len(icon_base64) % 4 else 0
            if padding_needed > 0:
                logger.debug("ServerIcon", f"Dodaję padding Base64: {padding_needed} znaków '='", log_type="DATA")
                icon_base64 += "=" * padding_needed
        except Exception as ex:
            logger.error("ServerIcon", f"Błąd podczas naprawiania paddingu Base64: {ex}", log_type="DATA")
            return None, None, None

        # Dekoduj Base64 do danych binarnych
        try:
            server_icon_data = base64.b64decode(icon_base64)
            icon_size = len(server_icon_data)

            # Oblicz hash MD5 ikony - będzie używany do porównywania i nazewnictwa
            icon_hash = hashlib.md5(server_icon_data).hexdigest()

            logger.debug("ServerIcon", f"Pomyślnie zdekodowano ikonę (rozmiar: {icon_size} bajtów, hash: {icon_hash})",
                         log_type="DATA")

            # Weryfikacja rozmiaru
            if icon_size < 100:
                logger.warning("ServerIcon", f"Podejrzanie mały rozmiar ikony: {icon_size} bajtów", log_type="DATA")
            elif icon_size > 1024 * 1024:  # Ponad 1 MB
                logger.warning("ServerIcon", f"Bardzo duża ikona: {icon_size} bajtów, może być problem z przesłaniem",
                               log_type="DATA")

            return server_icon_data, icon_format, icon_hash
        except Exception as ex:
            logger.error("ServerIcon", f"Błąd podczas dekodowania Base64: {ex}", log_type="DATA")
            return None, None, None

    except Exception as ex:
        logger.error("ServerIcon", f"Nieoczekiwany błąd podczas przetwarzania ikony: {ex}", log_type="DATA")
        return None, None, None


async def recover_saved_icon(server_address):
    """
    Próbuje odzyskać ostatnio zapisaną ikonę serwera z lokalnego systemu plików.

    Args:
        server_address (str): Adres serwera do identyfikacji ikony

    Returns:
        tuple: (bytes, str, str) - Dane binarne ikony, jej format i hash lub (None, None, None) w przypadku błędu
    """
    try:
        # Utwórz bezpieczną nazwę pliku na podstawie adresu serwera
        safe_server_name = "".join(c if c.isalnum() else "_" for c in server_address)
        icon_dir = SERVER_ICONS_DIR

        # Sprawdź, czy katalog z ikonami istnieje
        if not os.path.exists(icon_dir):
            logger.debug("ServerIcon", f"Katalog ikon {icon_dir} nie istnieje", log_type="DATA")
            return None, None, None

        # Sprawdź, czy istnieje główna ikona dla tego serwera
        # Sprawdzamy najpopularniejsze formaty
        for format_type in ["png", "jpg", "jpeg", "gif"]:
            main_icon_path = os.path.join(icon_dir, f"{safe_server_name}_current.{format_type}")
            if os.path.exists(main_icon_path):
                try:
                    # Odczytaj dane ikony
                    with open(main_icon_path, "rb") as f:
                        icon_data = f.read()

                    # Oblicz hash dla ikony
                    icon_hash = hashlib.md5(icon_data).hexdigest()

                    logger.info("ServerIcon",
                                f"Odzyskano zapisaną ikonę dla offline serwera (format: {format_type}, hash: {icon_hash})",
                                log_type="DATA")

                    return icon_data, format_type, icon_hash
                except Exception as ex:
                    logger.error("ServerIcon", f"Błąd podczas odczytywania zapisanej ikony {main_icon_path}: {ex}",
                                 log_type="DATA")

        # Jeśli nie znaleziono ikony dla żadnego formatu
        logger.debug("ServerIcon", f"Nie znaleziono zapisanej ikony dla serwera {server_address}", log_type="DATA")
        return None, None, None

    except Exception as ex:
        logger.error("ServerIcon", f"Nieoczekiwany błąd podczas odzyskiwania ikony: {ex}", log_type="DATA")
        return None, None, None


async def save_server_icon(server_icon_data, icon_format, icon_hash, server_address):
    """
    Inteligentnie zapisuje ikonę serwera, unikając duplikatów.

    Używa systemu hashowania, aby identyczne ikony były przechowywane tylko raz.
    Sprawdza, czy ikona się zmieniła przed zapisaniem jej ponownie.

    Args:
        server_icon_data (bytes): Dane binarne ikony
        icon_format (str): Format ikony (png, jpeg itp.)
        icon_hash (str): Hash MD5 danych ikony
        server_address (str): Adres serwera (używany w nazwie pliku)

    Returns:
        str: Ścieżka do zapisanego pliku lub None w przypadku błędu
    """
    if not server_icon_data or not icon_format or not icon_hash:
        logger.debug("ServerIcon", "Brak danych ikony do zapisania", log_type="DATA")
        return None

    try:
        # Utwórz katalog dla ikon, jeśli nie istnieje
        icon_dir = SERVER_ICONS_DIR
        os.makedirs(icon_dir, exist_ok=True)

        # Utwórz bezpieczną nazwę pliku na podstawie adresu serwera i hasha
        safe_server_name = "".join(c if c.isalnum() else "_" for c in server_address)

        # Używamy jednej głównej ikony dla serwera
        main_icon_path = os.path.join(icon_dir, f"{safe_server_name}_current.{icon_format}")

        # Dodajemy też wersję z hashem dla celów debugowania i porównania
        hash_icon_path = os.path.join(icon_dir, f"{safe_server_name}_{icon_hash}.{icon_format}")

        # Sprawdź, czy ikona z tym hashem już istnieje
        if os.path.exists(hash_icon_path):
            logger.debug("ServerIcon", f"Ikona o tym samym hashu już istnieje: {hash_icon_path}", log_type="DATA")

            # Aktualizuj główną ikonę, jeśli się różni
            if os.path.exists(main_icon_path):
                try:
                    with open(main_icon_path, "rb") as f:
                        current_main_data = f.read()

                    # Oblicz hash aktualnej głównej ikony
                    current_main_hash = hashlib.md5(current_main_data).hexdigest()

                    # Jeśli hash się różni, zaktualizuj główną ikonę
                    if current_main_hash != icon_hash:
                        with open(main_icon_path, "wb") as f:
                            f.write(server_icon_data)
                        logger.debug("ServerIcon", "Zaktualizowano główną ikonę serwera", log_type="DATA")
                except Exception as ex:
                    logger.warning("ServerIcon", f"Błąd podczas aktualizacji głównej ikony: {ex}", log_type="DATA")
            else:
                # Jeśli główna ikona nie istnieje, skopiuj istniejącą z hashem
                try:
                    shutil.copy2(hash_icon_path, main_icon_path)
                    logger.debug("ServerIcon", "Utworzono główną ikonę serwera", log_type="DATA")
                except Exception as ex:
                    logger.warning("ServerIcon", f"Błąd podczas kopiowania ikony: {ex}", log_type="DATA")

            return main_icon_path

        else:
            # Ta ikona jeszcze nie istnieje - zapisz nową wersję
            logger.debug("ServerIcon", f"Zapisuję nową ikonę: {hash_icon_path}", log_type="DATA")

            # Zapisz ikonę z hashem
            with open(hash_icon_path, "wb") as f:
                f.write(server_icon_data)

            # Zapisz/zaktualizuj główną ikonę
            with open(main_icon_path, "wb") as f:
                f.write(server_icon_data)

            # Usuń stare, nieużywane ikony, aby nie zabierały miejsca
            await clean_old_icons(icon_dir, safe_server_name, icon_hash)

            logger.debug("ServerIcon", "Zapisano nową wersję ikony i zaktualizowano główną ikonę", log_type="DATA")
            return main_icon_path
    except Exception as ex:
        logger.error("ServerIcon", f"Błąd podczas zapisywania ikony: {ex}", log_type="DATA")
        return None


async def clean_old_icons(icons_dir, server_name_prefix, current_hash, max_keep=5):
    """
    Usuwa stare ikony dla danego serwera, zachowując najnowsze.

    Args:
        icons_dir (str): Katalog ikon
        server_name_prefix (str): Prefiks nazwy pliku (nazwa serwera)
        current_hash (str): Hash obecnie używanej ikony (nie usuwaj tej)
        max_keep (int): Maksymalna liczba ikon do zachowania
    """
    try:
        # Nie usuwaj pliku głównej ikony
        current_file = f"{server_name_prefix}_current."

        # Znajdź wszystkie ikony hash dla tego serwera
        server_icons = []
        for filename in os.listdir(icons_dir):
            # Szukamy plików z hash - format: server_name_HASH.format
            if (filename.startswith(server_name_prefix + "_") and
                    current_hash not in filename and
                    not filename.startswith(current_file) and
                    "_" in filename and
                    any(filename.endswith(f".{ext}") for ext in ["png", "jpg", "jpeg", "gif"])):
                file_path = os.path.join(icons_dir, filename)
                file_mtime = os.path.getmtime(file_path)
                server_icons.append((file_mtime, file_path))

        # Posortuj według czasu modyfikacji (od najnowszego)
        server_icons.sort(reverse=True)

        # Usuń nadmiarowe ikony, zachowując najnowsze
        if len(server_icons) > max_keep:
            for _, file_path in server_icons[max_keep:]:
                try:
                    os.remove(file_path)
                    logger.debug("ServerIcon", f"Usunięto starą ikonę: {file_path}", log_type="DATA")
                except Exception as ex:
                    logger.warning("ServerIcon", f"Nie udało się usunąć starej ikony {file_path}: {ex}",
                                   log_type="DATA")
    except Exception as ex:
        logger.error("ServerIcon", f"Błąd podczas czyszczenia starych ikon: {ex}", log_type="DATA")


async def attach_server_icon(message, server_icon_data, icon_format):
    """
    Dołącza ikonę serwera do istniejącej wiadomości Discord lub edytuje wiadomość, dodając ikonę.

    Args:
        message (discord.Message): Wiadomość Discord do edycji
        server_icon_data (bytes): Dane binarne ikony
        icon_format (str): Format ikony

    Returns:
        bool: True, jeśli udało się dołączyć ikonę, False w przeciwnym przypadku
    """
    if not server_icon_data:
        return False

    try:
        # Utwórz plik do wysłania
        icon_file = discord.File(
            io.BytesIO(server_icon_data),
            filename=f"server_icon.{icon_format}"
        )

        # Pobierz istniejący embed
        embed = message.embeds[0] if message.embeds else None
        if not embed:
            logger.warning("ServerIcon", "Brak embeda w wiadomości, nie można dołączyć ikony", log_type="DISCORD")
            return False

        # Dołącz ikonę do embeda
        embed.set_thumbnail(url=f"attachment://server_icon.{icon_format}")

        # Edytuj wiadomość, dodając załącznik i zaktualizowany embed
        try:
            await message.edit(embed=embed, attachments=[icon_file])
            logger.info("ServerIcon", "Pomyślnie dołączono ikonę do wiadomości", log_type="DISCORD")
            return True
        except discord.HTTPException as ex:
            # Sprawdź, czy błąd dotyczy limitu rozmiaru załącznika
            if "Request entity too large" in str(ex):
                logger.warning("ServerIcon", "Ikona jest zbyt duża do wysłania jako załącznik", log_type="DISCORD")
            else:
                logger.error("ServerIcon", f"Błąd HTTP podczas edycji wiadomości z ikoną: {ex}", log_type="DISCORD")
            return False
        except Exception as ex:
            logger.error("ServerIcon", f"Błąd podczas edycji wiadomości z ikoną: {ex}", log_type="DISCORD")
            return False

    except Exception as ex:
        logger.error("ServerIcon", f"Nieoczekiwany błąd podczas dołączania ikony: {ex}", log_type="DISCORD")
        return False


async def update_last_seen(online_players):
    """
    Aktualizuje listę ostatnio widzianych graczy.

    Funkcja śledzi, którzy gracze są obecnie online i kiedy byli ostatnio widziani.
    Dla graczy online aktualizuje znacznik czasu na aktualny, a dla graczy,
    którzy wyszli z serwera, zachowuje ostatni znany czas ich aktywności.

    Args:
        online_players (list): Lista graczy obecnie online na serwerze

    Returns:
        dict: Zaktualizowany słownik z informacjami o ostatnio widzianych graczach
    """
    global last_seen, last_known_online_time
    current_time = get_warsaw_time()

    # Jeśli są jacyś gracze online, zaktualizuj czas ostatniego stanu online
    if online_players:
        last_known_online_time = current_time

    # Pobierz aktualną listę graczy, którzy są zapisani w last_seen
    known_players = set(last_seen.keys())
    current_players = set(online_players)

    # Aktualizuj czas dla obecnie online graczy
    for player in online_players:
        if player in last_seen:
            logger.debug("Players", f"Aktualizacja czasu dla aktywnego gracza: {player}", log_type="DATA")
        else:
            logger.player_activity(player, "online")
        last_seen[player] = current_time

    # Sprawdź, którzy gracze są teraz offline
    for player in known_players - current_players:
        if player in last_seen:
            logger.player_activity(player, "offline", format_time(last_seen[player]))

    logger.debug("Players", "Zaktualizowano informacje o ostatnio widzianych graczach",
                 online_players=online_players,
                 last_seen={p: format_time(t) for p, t in last_seen.items()})

    # Zapisz dane
    save_bot_data()

    return last_seen


def create_minecraft_embed(server_data, last_seen_data):
    """
    Tworzy embed z informacjami o serwerze Minecraft.

    Funkcja generuje pięknie sformatowany embed Discord zawierający
    informacje o statusie serwera, liczbie graczy, liście graczy online
    oraz graczy, którzy byli ostatnio widziani.

    Args:
        server_data (dict): Dane o serwerze pobrane z API
        last_seen_data (dict): Słownik z informacjami o ostatnio widzianych graczach

    Returns:
        discord.Embed: Gotowy embed do wysłania na kanał Discord
    """
    current_time = get_warsaw_time()

    # Dodane logowanie dla debugowania danych serwera
    logger.debug("EmbedCreation", "Rozpoczęcie tworzenia embeda",
                 raw_server_data=server_data)

    # Sprawdź, czy wystąpił błąd API
    if "error" in server_data and "online" not in server_data:
        # Tworzenie embeda z informacją o błędzie
        embed = discord.Embed(
            title=f"Status serwera Minecraft: {MC_SERVER_ADDRESS}",
            color=discord.Color.light_gray(),
            timestamp=current_time
        )

        # Dodaj informację o błędzie
        error_msg = server_data.get("error", "Nieznany błąd")
        embed.add_field(name="⚠️ Błąd API", value=f"```{error_msg}```", inline=False)
        embed.add_field(name="Status", value="Nieznany (błąd API)", inline=False)

        # Dodaj ostatnio widzianych graczy, jeśli są dostępni
        if last_seen_data:
            last_seen_text = ""
            offline_players = []

            for player, last_time in last_seen_data.items():
                last_seen_text += f"{player}: {format_time(last_time)}\n"
                offline_players.append(f"{player}: {format_time(last_time)}")

            if last_seen_text:
                embed.add_field(name="Ostatnio widziani:", value=f"```{last_seen_text}```", inline=False)
                logger.debug("Embed", "Dodano listę ostatnio widzianych graczy", offline_players=offline_players)

        # Dodaj informację o wersji bota
        embed.set_footer(text=f"Bot v{BOT_VERSION}")

        return embed

    # Standardowy kod dla poprawnej odpowiedzi
    # Sprawdź rzeczywisty status serwera
    is_online = server_data.get("online", False)

    # Dodane dodatkowe logowanie dla graczy
    player_list = server_data.get("players", {}).get("list", []) if is_online else []
    logger.debug("EmbedCreation", f"Lista graczy z API: {player_list}",
                 player_count=len(player_list),
                 player_data=server_data.get("players", {}))

    # Ustawienie koloru embeda
    if is_online:
        if player_list:
            color = discord.Color.green()  # Serwer online z graczami
            logger.debug("Embed", "Tworzenie zielonego embeda (serwer online z graczami)")
        else:
            color = discord.Color.gold()  # Serwer online bez graczy
            logger.debug("Embed", "Tworzenie złotego embeda (serwer online bez graczy)")
    else:
        color = discord.Color.red()  # Serwer offline
        logger.debug("Embed", "Tworzenie czerwonego embeda (serwer offline)")

    # Tworzenie embeda
    embed = discord.Embed(
        title=f"Status serwera Minecraft: {MC_SERVER_ADDRESS}",
        color=color,
        timestamp=current_time
    )

    # Status serwera
    status = "🟢 ONLINE" if is_online else "🔴 OFFLINE"
    embed.add_field(name="Status", value=status, inline=False)

    # Liczba graczy (niezależnie czy serwer online, czy nie)
    players_online = server_data.get("players", {}).get("online", 0) if is_online else 0

    # Użyj zapamiętanej maksymalnej liczby graczy, jeśli serwer jest offline
    if is_online:
        players_max = server_data.get("players", {}).get("max", max_players)
    else:
        players_max = max_players

    embed.add_field(name="Gracze", value=f"{players_online}/{players_max}", inline=True)

    # Lista graczy
    if is_online and player_list:
        # Dodajmy numerację graczy dla lepszej czytelności
        players_value = ""
        for idx, player in enumerate(player_list, 1):
            players_value += f"{idx}. {player}\n"

        # Dodajmy informację o liczbie graczy w nazwie pola
        player_count = len(player_list)
        field_name = f"Lista graczy online ({player_count})"

        # Sprawdźmy długość listy graczy - Discord ma limity na pola embed
        if len(players_value) > 900:  # Bezpieczny limit dla wartości pola embed
            # Jeśli lista jest zbyt długa, podzielmy ją
            first_part = ""
            for idx, player in enumerate(player_list[:5], 1):  # Pokaż tylko pierwszych 5
                first_part += f"{idx}. {player}\n"

            embed.add_field(name=field_name, value=f"```{first_part}... i {player_count - 5} więcej```", inline=False)
            logger.debug("Embed", f"Lista graczy jest zbyt długa, pokazuję tylko 5 pierwszych z {player_count}",
                         players=player_list)
        else:
            # Standardowo pokazujemy wszystkich graczy
            embed.add_field(name=field_name, value=f"```{players_value}```", inline=False)
            logger.debug("Embed", f"Dodano {player_count} graczy do listy", players=player_list)

        # Dodajmy dodatkowe logowanie dla każdego gracza
        for player in player_list:
            logger.debug("EmbedPlayer", f"Dodawanie gracza do embeda: {player}")
    else:
        embed.add_field(name="Lista graczy online", value="Brak graczy online", inline=False)
        logger.debug("Embed", "Brak graczy online")

    # Ostatnio widziani gracze
    if last_seen_data:
        last_seen_text = ""
        offline_players = []

        for player, last_time in last_seen_data.items():
            if not is_online or player not in player_list:  # Wszyscy gracze, gdy serwer offline, albo tylko nieobecni, gdy online
                last_seen_text += f"{player}: {format_time(last_time)}\n"
                offline_players.append(f"{player}: {format_time(last_time)}")

        if last_seen_text:
            embed.add_field(name="Ostatnio widziani:", value=f"```{last_seen_text}```", inline=False)
            logger.debug("Embed", "Dodano listę ostatnio widzianych graczy", offline_players=offline_players)

    # Dodaj informację o wersji bota
    embed.set_footer(text=f"Bot v{BOT_VERSION}")

    return embed


async def find_and_delete_previous_message():
    """
    Znajduje i usuwa poprzednią wiadomość bota na kanale.

    Funkcja jest używana podczas uruchamiania bota, aby usunąć
    ostatnią wysłaną przez niego wiadomość i rozpocząć pracę z nową.

    Returns:
        bool: True, jeśli znaleziono i usunięto wiadomość, False w przeciwnym razie
    """
    global last_embed_id

    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error("Cleanup", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
        return False

    try:
        # Sprawdź zapisany ID ostatniej wiadomości
        if last_embed_id is not None and isinstance(last_embed_id, int):
            try:
                message = await channel.fetch_message(last_embed_id)
                await message.delete()
                logger.info("Discord", f"Usunięto wiadomość (ID: {last_embed_id}) aby dodać ikonę",
                            log_type="DISCORD")
                last_embed_id = None
                return True
            except discord.NotFound:
                logger.warning("Cleanup", f"Nie znaleziono wiadomości o ID {last_embed_id}", log_type="BOT")
                last_embed_id = None  # Resetujemy, bo wiadomość nie istnieje
                return False
            except Exception as ex:
                logger.error("Cleanup", f"Błąd podczas usuwania wiadomości: {ex}", log_type="BOT")
                # Nie resetujemy last_embed_id, może się uda następnym razem
                return False

        # Jeśli nie ma zapisanego ID wiadomości
        return False
    except Exception as ex:
        logger.error("Cleanup", f"Ogólny błąd podczas szukania i usuwania wiadomości: {ex}", log_type="BOT")
        return False


@client.event
async def on_ready():
    """
    Funkcja wywoływana po poprawnym uruchomieniu bota.

    Inicjalizuje bota, ładuje zapisane dane, usuwa poprzednią wiadomość,
    ustawia początkowy status i uruchamia zadanie cyklicznego sprawdzania serwera.
    """
    logger.bot_status("ready", client.user)

    # Ładuj zapisane dane
    load_bot_data()

    # Sprawdź, czy kanał istnieje
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error("DiscordBot", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
        return

    logger.info("DiscordBot", f"Połączono z kanałem '{channel.name}' (ID: {CHANNEL_ID})", log_type="BOT")

    # Usuń poprzednią wiadomość - tylko przy starcie bota
    await find_and_delete_previous_message()

    # Ustaw początkowy status jako "oczekiwanie" do czasu pierwszego sprawdzenia serwera
    await client.change_presence(
        status=discord.Status.idle,
        activity=discord.Game(name="Sprawdzanie stanu serwera...")
    )
    logger.info("BotStatus", "Ustawiono początkowy status bota", log_type="BOT")

    # Uruchom zadanie cyklicznego sprawdzania serwera
    logger.info("Tasks", "Uruchamianie zadania sprawdzania serwera co 5 minut", log_type="BOT")
    check_server.start()

    # Synchronizacja komend slash (/) dla wszystkich serwerów
    try:
        if GUILD_ID:  # Jeśli podano ID serwera, synchronizuj tylko dla tego serwera (szybciej)
            guild = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            logger.info("SlashCommands", f"Zsynchronizowano komendy slash dla serwera {GUILD_ID}", log_type="BOT")
        else:  # Jeśli nie podano ID serwera, synchronizuj globalnie (może potrwać do godziny)
            await tree.sync()
            logger.info("SlashCommands", "Zsynchronizowano komendy slash globalnie", log_type="BOT")
    except Exception as ex:
        logger.error("SlashCommands", f"Błąd podczas synchronizacji komend slash: {ex}", log_type="BOT")


@tasks.loop(minutes=5)
async def check_server():
    """
    Zadanie cyklicznie sprawdzające stan serwera i aktualizujące informacje.
    """
    global last_embed_id

    try:
        logger.debug("Tasks", "Rozpoczęcie zadania sprawdzania serwera", log_type="BOT")

        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            logger.error("Tasks", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
            return

        # Pobierz status serwera
        server_data = await check_minecraft_server()

        # Aktualizuj status bota na podstawie stanu serwera
        await update_bot_status(server_data)

        # Aktualizuj informacje o ostatnio widzianych graczach
        if server_data.get("online", False):
            player_list = server_data.get("players", {}).get("list", [])
            await update_last_seen(player_list)

        # Przetwórz ikonę serwera (jeśli jest dostępna)
        # POPRAWKA: Dodajemy trzeci parametr (icon_hash)
        server_icon_data, icon_format, icon_hash = await process_server_icon(server_data)
        has_valid_icon = server_icon_data is not None

        # Ścieżka do ikony - używana w przypadku błędów wysyłania
        icon_path = None

        if has_valid_icon and ENABLE_SERVER_ICONS:
            # Zapisz ikonę lokalnie, unikając duplikatów
            if SAVE_SERVER_ICONS:
                icon_path = await save_server_icon(server_icon_data, icon_format, icon_hash, MC_SERVER_ADDRESS)
                if icon_path:
                    logger.debug("Tasks", f"Użyto ikony z pliku: {icon_path}", log_type="BOT")

        # Utwórz nowy embed
        embed = create_minecraft_embed(server_data, last_seen)

        # Edytuj istniejącą wiadomość lub wyślij nową
        icon_attached = False
        message = None

        # Strategia: zawsze edytuj istniejącą wiadomość, nie usuwaj i nie twórz nowej
        if last_embed_id is not None and isinstance(last_embed_id, int):
            try:
                logger.debug("ServerIcon", f"Próbuję zaktualizować wiadomość {last_embed_id} z embedem",
                             log_type="DISCORD")
                message = await channel.fetch_message(last_embed_id)

                # Najpierw zaktualizuj sam embed bez ikony
                await message.edit(embed=embed)
                logger.discord_message("edited", last_embed_id, channel=channel.name)

                # Teraz spróbuj dodać ikonę, jeśli jest dostępna i włączona
                if has_valid_icon and ENABLE_SERVER_ICONS:
                    try:
                        logger.debug("ServerIcon", f"Próbuję dołączyć ikonę (hash: {icon_hash}) do wiadomości",
                                     log_type="DISCORD")
                        icon_attached = await attach_server_icon(message, server_icon_data, icon_format)
                    except Exception as icon_error:
                        logger.error("ServerIcon", f"Błąd podczas dołączania ikony: {icon_error}", log_type="DISCORD")
                        # Kontynuuj, nawet jeśli ikona nie została dołączona

                # Zapisz dane po aktualizacji
                save_bot_data()
                return

            except discord.NotFound:
                logger.warning("Discord", f"Wiadomość o ID {last_embed_id} nie została znaleziona. Wysyłam nową.",
                               log_type="DISCORD")
                last_embed_id = None
            except Exception as ex:
                logger.error("Discord", f"Błąd podczas edycji wiadomości: {ex}.", log_type="DISCORD")
                last_embed_id = None

        # Jeśli doszliśmy tutaj, musimy wysłać nową wiadomość
        try:
            # Spróbuj wysłać wiadomość z ikoną, jeśli jest dostępna i włączona
            if has_valid_icon and ENABLE_SERVER_ICONS:
                try:
                    # Przygotuj plik ikony
                    icon_file = discord.File(
                        io.BytesIO(server_icon_data),
                        filename=f"server_icon.{icon_format}"
                    )

                    # Ustaw miniaturę w embedzie
                    embed.set_thumbnail(url=f"attachment://server_icon.{icon_format}")

                    # Wyślij embed z ikoną
                    message = await channel.send(embed=embed, file=icon_file)
                    icon_attached = True
                    logger.debug("ServerIcon", f"Pomyślnie wysłano nową wiadomość z ikoną (hash: {icon_hash})",
                                 log_type="DISCORD")
                except Exception as icon_error:
                    logger.error("ServerIcon", f"Nie udało się wysłać wiadomości z ikoną: {icon_error}",
                                 log_type="DISCORD")
                    # Jeśli wysłanie z ikoną się nie powiedzie, wyślij bez ikony
                    message = await channel.send(embed=embed)
            else:
                # Wyślij wiadomość bez ikony
                message = await channel.send(embed=embed)

            logger.discord_message("sent", message.id, channel=channel.name)
            last_embed_id = message.id

            # Dodaj dodatkowe informacje o ikonie do logu
            if has_valid_icon and ENABLE_SERVER_ICONS:
                logger.debug("ServerIcon",
                             f"Status ikony dla nowej wiadomości: {'dołączona' if icon_attached else 'nie dołączona'}",
                             log_type="DISCORD")

            # Zapisz dane po wysłaniu nowej wiadomości
            save_bot_data()

        except Exception as send_error:
            logger.critical("Tasks", f"Nie udało się wysłać nowej wiadomości: {send_error}", log_type="BOT")

    except Exception as ex:
        logger.critical("Tasks", f"Wystąpił błąd w funkcji check_server: {ex}", log_type="BOT")


async def check_server_for_command():
    """
    Specjalna wersja funkcji check_server do użycia w komendzie /ski.
    Sprawdza stan serwera i aktualizuje embed, ale nie aktualizuje wszystkich powiązanych danych.
    Zawiera rozszerzoną obsługę błędów i ikony serwera.
    """
    global last_embed_id

    try:
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            logger.error("Commands", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
            return False

        # Pobierz status serwera
        server_data = await check_minecraft_server()

        # Aktualizuj status bota
        await update_bot_status(server_data)

        # Aktualizuj informacje o ostatnio widzianych graczach
        if server_data.get("online", False):
            player_list = server_data.get("players", {}).get("list", [])
            await update_last_seen(player_list)

        # Przetwórz ikonę serwera (jeśli jest dostępna)
        # POPRAWKA: Dodajemy trzeci parametr (icon_hash)
        server_icon_data, icon_format, icon_hash = await process_server_icon(server_data)
        has_valid_icon = server_icon_data is not None

        if has_valid_icon:
            logger.debug("CommandServerIcon", f"Znaleziono ikonę w formacie {icon_format}", log_type="DATA")
        else:
            logger.debug("CommandServerIcon", "Brak ikony serwera lub serwer offline", log_type="DATA")

        # Utwórz nowy embed
        embed = create_minecraft_embed(server_data, last_seen)

        # Edytuj istniejącą lub wyślij nową wiadomość
        icon_attached = False
        message = None

        # Edytuj istniejącą wiadomość, jeśli istnieje
        if last_embed_id is not None and isinstance(last_embed_id, int):
            try:
                message = await channel.fetch_message(last_embed_id)

                # Najpierw aktualizujemy embed bez ikony
                await message.edit(embed=embed)
                logger.discord_message("edited", last_embed_id, channel=channel.name)

                # Następnie próbujemy dodać ikonę, jeśli jest dostępna
                if has_valid_icon:
                    try:
                        icon_attached = await attach_server_icon(message, server_icon_data, icon_format)
                        logger.debug("CommandServerIcon",
                                     f"Ikona {'została dołączona' if icon_attached else 'nie została dołączona'} do zaktualizowanej wiadomości",
                                     log_type="DISCORD")
                    except Exception as icon_error:
                        logger.error("CommandServerIcon", f"Błąd podczas dołączania ikony: {icon_error}",
                                     log_type="DISCORD")

                save_bot_data()
                return True

            except discord.NotFound:
                logger.warning("Commands", f"Wiadomość o ID {last_embed_id} nie została znaleziona. Wysyłam nową.",
                               log_type="DISCORD")
                last_embed_id = None
            except Exception as ex:
                logger.error("Commands", f"Błąd podczas edycji wiadomości: {ex}.", log_type="DISCORD")
                last_embed_id = None

        # Wysyłamy nową wiadomość, jeśli nie udało się edytować istniejącej
        try:
            # Spróbuj wysłać z ikoną, jeśli jest dostępna
            if has_valid_icon:
                try:
                    # Przygotuj plik ikony
                    icon_file = discord.File(
                        io.BytesIO(server_icon_data),
                        filename=f"server_icon.{icon_format}"
                    )

                    # Ustaw miniaturę w embedzie
                    embed.set_thumbnail(url=f"attachment://server_icon.{icon_format}")

                    # Wyślij embed z ikoną
                    message = await channel.send(embed=embed, file=icon_file)
                    icon_attached = True
                    logger.debug("CommandServerIcon", "Wysłano nową wiadomość z ikoną", log_type="DISCORD")
                except Exception as icon_error:
                    logger.error("CommandServerIcon", f"Nie udało się wysłać ikony, wysyłam bez ikony: {icon_error}",
                                 log_type="DISCORD")
                    message = await channel.send(embed=embed)
            else:
                # Wyślij bez ikony
                message = await channel.send(embed=embed)

            logger.discord_message("sent", message.id, channel=channel.name)
            last_embed_id = message.id
            save_bot_data()
            return True

        except Exception as send_error:
            logger.error("Commands", f"Nie udało się wysłać nowej wiadomości: {send_error}", log_type="DISCORD")
            return False

    except Exception as ex:
        logger.error("Commands", f"Błąd podczas aktualizacji stanu serwera: {ex}", log_type="BOT")
        return False


async def update_bot_status(server_data):
    """
    Aktualizuje status bota Discord w zależności od stanu serwera Minecraft.

    Status bota jest ustawiany następująco:
    - Online (Aktywny): Gdy serwer jest online i są jacyś gracze
    - Idle (Zaraz wracam): Gdy serwer jest online, ale nie ma graczy
    - DND (Nie przeszkadzać): Gdy serwer jest offline

    Dodatkowo aktywność bota pokazuje liczbę graczy lub informację o stanie serwera.

    Args:
        server_data (dict): Dane o serwerze pobrane z API
    """
    try:
        # Pobierz dostęp do zmiennej globalnej
        global max_players

        # Sprawdź status serwera
        is_online = server_data.get("online", False)

        # Pobierz dane o graczach
        players = server_data.get("players", {})
        player_count = players.get("online", 0) if is_online else 0
        players_max = players.get("max", max_players)  # Używamy zmiennej globalnej jako fallback

        # Ustaw odpowiedni status i aktywność
        if is_online:
            if player_count > 0:
                # Serwer online z graczami — status Aktywny
                status = discord.Status.online
                activity_text = f"{player_count}/{players_max} graczy online"
                logger.info("BotStatus", f"Zmieniam status na ONLINE - {activity_text}", log_type="BOT")
            else:
                # Serwer online bez graczy - status Zaraz wracam
                status = discord.Status.idle
                activity_text = "Serwer jest pusty"
                logger.info("BotStatus", f"Zmieniam status na IDLE - {activity_text}", log_type="BOT")
        else:
            # Serwer offline - status Nie przeszkadzać
            status = discord.Status.dnd
            activity_text = "Serwer offline"
            logger.info("BotStatus", f"Zmieniam status na DND - {activity_text}", log_type="BOT")

        # Ustaw aktywność - "gra w..."
        activity = discord.Game(name=activity_text)

        # Aktualizuj status bota
        await client.change_presence(status=status, activity=activity)

    except Exception as ex:
        logger.error("BotStatus", f"Błąd podczas aktualizacji statusu bota: {ex}", log_type="BOT")


@tree.command(
    name="ski",
    description="Aktualizuje informacje o stanie serwera Minecraft"
)
async def refresh_minecraft_status(interaction: discord.Interaction):
    """
    Komenda slash do natychmiastowej aktualizacji informacji o serwerze.

    Aktualizuje embeda i status bota na podstawie aktualnego stanu serwera,
    wysyłając zapytanie do API mcsv.

    Args:
        interaction (discord.Interaction): Obiekt interakcji z Discord
    """
    try:
        # Zapisz informację o użyciu komendy
        user_id = interaction.user.id
        user_name = interaction.user.name
        current_time = datetime.datetime.now(warsaw_tz)

        logger.info("Commands", f"Użytkownik {user_name} (ID: {user_id}) użył komendy /ski", log_type="BOT")

        # Sprawdź cooldown (ograniczenie nadużyć)
        if user_id in last_command_usage:
            time_diff = (current_time - last_command_usage[user_id]).total_seconds()
            if time_diff < COMMAND_COOLDOWN and not interaction.user.guild_permissions.administrator:
                remaining = int(COMMAND_COOLDOWN - time_diff)
                logger.warning("Commands",
                               f"Użytkownik {user_name} próbował użyć komendy zbyt szybko (pozostało {remaining}s)",
                               log_type="BOT")
                await interaction.response.send_message(
                    f"⏳ Proszę poczekać jeszcze {remaining} sekund przed ponownym użyciem tej komendy.",
                    ephemeral=True
                )
                return

        # Zapisz czas użycia komendy
        last_command_usage[user_id] = current_time

        # Sprawdź, czy jesteśmy na odpowiednim kanale lub, czy użytkownik ma uprawnienia administratora
        if interaction.channel_id != CHANNEL_ID and not interaction.user.guild_permissions.administrator:
            channel = client.get_channel(CHANNEL_ID)
            channel_name = channel.name if channel else f"#{CHANNEL_ID}"

            logger.warning("Commands",
                           f"Komenda wywołana na niewłaściwym kanale: {interaction.channel.name} przez {user_name}",
                           log_type="BOT")

            await interaction.response.send_message(
                f"⚠️ Ta komenda działa tylko na kanale <#{CHANNEL_ID}> ({channel_name}).",
                ephemeral=True
            )
            return

        # Odpowiedz na interakcję, by uniknąć timeoutu
        await interaction.response.defer(ephemeral=True)

        # Pobierz status serwera
        server_data = await check_minecraft_server()

        # Aktualizuj status bota
        await update_bot_status(server_data)

        # Aktualizuj informacje o ostatnio widzianych graczach
        if server_data.get("online", False):
            player_list = server_data.get("players", {}).get("list", [])
            await update_last_seen(player_list)

        # Zaktualizuj lub wyślij nową wiadomość embed
        success = await check_server_for_command()

        # Odpowiedz użytkownikowi
        if success:
            await interaction.followup.send("✅ Informacje o serwerze zostały zaktualizowane.", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Wystąpił problem podczas aktualizacji informacji o serwerze.",
                                            ephemeral=True)

        logger.info("Commands", f"Pomyślnie wykonano komendę /ski dla {user_name}", log_type="BOT")

    except Exception as ex:
        # Złap wszystkie pozostałe błędy
        error_msg = str(ex)
        logger.critical("Commands", f"Nieoczekiwany błąd w komendzie /ski: {error_msg}", log_type="BOT")

        # Próbuj odpowiedzieć użytkownikowi, jeśli to jeszcze możliwe
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ Wystąpił nieoczekiwany błąd podczas aktualizacji informacji o serwerze.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Wystąpił nieoczekiwany błąd podczas aktualizacji informacji o serwerze.",
                    ephemeral=True
                )
        except Exception as follow_up_error:
            logger.critical("Commands",
                            f"Nie można wysłać informacji o błędzie: {follow_up_error}",
                            log_type="BOT")


# Uruchom bota
if __name__ == "__main__":
    # Upewnij się, że katalog logów istnieje
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    logger.bot_status("connecting")
    try:
        client.run(DISCORD_TOKEN)
    except Exception as e:
        logger.bot_status("error", str(e))
