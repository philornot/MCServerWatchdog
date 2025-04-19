import base64
import datetime
import io
import os
import pickle

import aiohttp
import discord
import pytz
from discord import File
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
LOG_FILE = os.getenv("LOG_FILE", "logs/mcserverwatch.log")  # Ścieżka do pliku logów
DATA_FILE = os.getenv("DATA_FILE", "data/bot_data.pickle")  # Plik do zapisywania danych bota
GUILD_ID = os.getenv("GUILD_ID")  # ID serwera Discord, opcjonalnie dla szybszego rozwoju komend

# Inicjalizacja loggera
logger = PrettyLogger(log_file=LOG_FILE, console_level="INFO", file_level="DEBUG")

# Słownik do przechowywania informacji o ostatniej aktywności graczy
last_seen = {}

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
        "last_known_online_time": last_known_online_time
    }
    try:
        with open(DATA_FILE, "wb") as f:
            pickle.dump(data, f)
        logger.debug("DataStorage", f"Zapisano dane bota do {DATA_FILE}", log_type="CONFIG")
    except Exception as e:
        logger.error("DataStorage", f"Błąd podczas zapisywania danych: {e}", log_type="CONFIG")


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
    except Exception as e:
        logger.error("DataStorage", f"Błąd podczas ładowania danych: {e}", log_type="CONFIG")


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

    Funkcja łączy się z API mcsrvstat.us aby pobrać informacje o stanie serwera.
    Wykonuje dodatkową weryfikację prawdziwego statusu serwera poprzez analizę
    wiadomości MOTD i wersji. Implementuje także mechanizm stabilizacji statusu,
    aby zapobiec fałszywym raportom offline/online.

    Returns:
        dict: Słownik zawierający informacje o serwerze, w tym jego prawdziwy status
    """
    global max_players, last_known_online_time, last_seen

    # Przechowujemy czas ostatniego znanego stanu online
    current_time = get_warsaw_time()
    api_url = f"https://api.mcsrvstat.us/2/{MC_SERVER_ADDRESS}:{MC_SERVER_PORT}"

    try:
        logger.debug("ServerCheck", f"Sprawdzanie stanu serwera {MC_SERVER_ADDRESS}:{MC_SERVER_PORT}", log_type="API")

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.api_request(api_url, response=data, status=response.status)

                    # Zapisz maksymalną liczbę graczy, jeśli jest dostępna
                    players_data = data.get("players", {})
                    if players_data and "max" in players_data and players_data["max"] > 0:
                        max_players = players_data["max"]
                        logger.debug("ServerCheck", f"Zaktualizowano maksymalną liczbę graczy: {max_players}",
                                     log_type="DATA")

                    # Dodatkowe sprawdzenia wiarygodności statusu
                    reported_online = data.get("online", False)

                    # Weryfikacja statusu na podstawie MOTD i wersji
                    if reported_online:
                        motd_clean = data.get("motd", {}).get("clean", [""])
                        motd_text = motd_clean[0].lower() if motd_clean else ""
                        version_text = data.get("version", "").lower()

                        # Jeśli MOTD lub wersja wskazują, że serwer jest offline, nadpisz status online
                        if "offline" in motd_text or "offline" in version_text:
                            logger.debug("ServerCheck",
                                         "Serwer zgłoszony jako online, ale MOTD/wersja wskazuje na offline. Nadpisuję status.",
                                         log_type="API",
                                         motd=motd_text,
                                         version=version_text)
                            data["online"] = False
                            reported_online = False

                    # Mechanizm stabilizacji statusu - sprawdź listę graczy i ostatnie czasy aktywności
                    player_list = data.get("players", {}).get("list", []) if reported_online else []

                    # Jeśli API raportuje online i mamy graczy, aktualizuj czas ostatniego znanego stanu online
                    if reported_online and player_list:
                        last_known_online_time = current_time
                        logger.debug("ServerCheck", "Serwer online z graczami, aktualizacja czasu online",
                                     log_type="DATA")

                    # Jeśli API raportuje offline, ale widzieliśmy graczy w ostatnich 5 minutach, uznaj serwer za online
                    elif not reported_online and last_known_online_time:
                        time_difference = (current_time - last_known_online_time).total_seconds() / 60

                        # Jeśli ostatnia aktywność była mniej niż 5 minut temu, nadal uznajemy serwer za online
                        if time_difference < 5:
                            # Sprawdź, czy mamy aktywnych graczy w ciągu ostatnich 5 minut
                            recent_players = False
                            for player, last_time in last_seen.items():
                                player_time_diff = (current_time - last_time).total_seconds() / 60
                                if player_time_diff < 5:
                                    recent_players = True
                                    break

                            if recent_players:
                                logger.debug("ServerCheck",
                                             f"API zgłasza offline, ale widzieliśmy graczy w ciągu ostatnich 5 minut. Wymuszam status online.",
                                             log_type="API",
                                             last_online_time=format_time(last_known_online_time),
                                             time_diff=time_difference)
                                data["online"] = True

                                # Odtwarzamy dane o graczach z ostatniego znanego stanu
                                if "players" not in data:
                                    data["players"] = {}

                                active_players = []
                                for player, last_time in last_seen.items():
                                    player_time_diff = (current_time - last_time).total_seconds() / 60
                                    if player_time_diff < 5:
                                        active_players.append(player)

                                if active_players:
                                    data["players"]["online"] = len(active_players)
                                    data["players"]["list"] = active_players

                    # Logowanie szczegółowych informacji o serwerze
                    if data.get("online", False):
                        logger.server_status(True, data)
                    else:
                        logger.server_status(False, data)

                    return data
                else:
                    error_msg = f"Błąd API: {response.status}"
                    # Dla kodu 429 dodaj bardziej przyjazną wiadomość
                    if response.status == 429:
                        error_msg = "Zbyt wiele zapytań do API (kod 429). Proszę spróbować ponownie za chwilę."

                    logger.api_request(api_url, status=response.status, error=error_msg)
                    return {"online": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Wyjątek: {str(e)}"
        logger.api_request(api_url, error=error_msg)
        return {"online": False, "error": error_msg}


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

    # Sprawdź czy wystąpił błąd API
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

    # Liczba graczy (niezależnie czy serwer online czy nie)
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
            if not is_online or player not in player_list:  # Wszyscy gracze gdy serwer offline, albo tylko nieobecni gdy online
                last_seen_text += f"{player}: {format_time(last_time)}\n"
                offline_players.append(f"{player}: {format_time(last_time)}")

        if last_seen_text:
            embed.add_field(name="Ostatnio widziani:", value=f"```{last_seen_text}```", inline=False)
            logger.debug("Embed", "Dodano listę ostatnio widzianych graczy", offline_players=offline_players)

    return embed


async def find_and_delete_previous_message():
    """
    Znajduje i usuwa poprzednią wiadomość bota na kanale.

    Funkcja jest używana podczas uruchamiania bota, aby usunąć
    ostatnią wysłaną przez niego wiadomość i rozpocząć pracę z nową.

    Returns:
        bool: True jeśli znaleziono i usunięto wiadomość, False w przeciwnym razie
    """
    global last_embed_id

    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error("Cleanup", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
        return None

    try:
        # Sprawdź zapisany ID ostatniej wiadomości
        if last_embed_id:
            try:
                message = await channel.fetch_message(last_embed_id)
                await message.delete()
                logger.info("Discord", f"Usunięto wiadomość (ID: {last_embed_id}) aby dodać ikonę",
                            log_type="DISCORD")
                last_embed_id = None
                return True
            except discord.NotFound:
                logger.warning("Cleanup", f"Nie znaleziono wiadomości o ID {last_embed_id}", log_type="BOT")
            except Exception as e:
                logger.error("Cleanup", f"Błąd podczas usuwania wiadomości: {e}", log_type="BOT")

        # Jeśli nie ma zapisanego ID lub wystąpił błąd, spróbuj znaleźć ostatnią wiadomość bota
        async for message in channel.history(limit=50):
            if message.author.id == client.user.id and message.embeds:
                for embed in message.embeds:
                    if f"Status serwera Minecraft: {MC_SERVER_ADDRESS}" in (embed.title or ""):
                        await message.delete()
                        logger.info("Cleanup", f"Usunięto znalezioną wiadomość bota (ID: {message.id})", log_type="BOT")
                        return True

        logger.info("Cleanup", "Nie znaleziono poprzedniej wiadomości do usunięcia", log_type="BOT")
        return False
    except Exception as e:
        logger.error("Cleanup", f"Ogólny błąd podczas szukania i usuwania wiadomości: {e}", log_type="BOT")
        return False


@client.event
async def on_ready():
    """
    Funkcja wywoływana po poprawnym uruchomieniu bota.

    Inicjalizuje bota, ładuje zapisane dane, usuwa poprzednią wiadomość
    i uruchamia zadanie cyklicznego sprawdzania serwera.
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
    except Exception as e:
        logger.error("SlashCommands", f"Błąd podczas synchronizacji komend slash: {e}", log_type="BOT")


@tasks.loop(minutes=5)
async def check_server():
    """
    Zadanie cyklicznie sprawdzające stan serwera i aktualizujące informacje.

    Ta funkcja jest wywoływana co 5 minut. Pobiera aktualny stan serwera,
    aktualizuje informacje o graczach i edytuje istniejący embed zamiast
    tworzenia nowych wiadomości.
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

        # Aktualizuj informacje o ostatnio widzianych graczach
        if server_data.get("online", False):
            player_list = server_data.get("players", {}).get("list", [])
            await update_last_seen(player_list)

        # Utwórz nowy embed
        embed = create_minecraft_embed(server_data, last_seen)

        # Ikona serwera (tylko do przechowywania, nie będziemy wysyłać jako załącznik)
        server_icon = None
        if server_data.get("online", False) and "icon" in server_data:
            try:
                icon_base64 = server_data["icon"].split(',')[-1] if "," in server_data["icon"] else server_data["icon"]
                # Napraw padding Base64 jeśli potrzeba
                padding = 4 - (len(icon_base64) % 4) if len(icon_base64) % 4 else 0
                icon_base64 += "=" * padding
                # Dekoduj i przechowuj jako dane binarne (nie tworzymy załącznika)
                server_icon = base64.b64decode(icon_base64)
                logger.debug("Embed", "Przygotowano dane ikony serwera")
            except Exception as e:
                logger.warning("Embed", f"Nie udało się zdekodować ikony serwera: {e}")
                server_icon = None

        # Strategia: zawsze edytuj istniejącą wiadomość, nie usuwaj i nie twórz nowej
        if last_embed_id:
            try:
                message = await channel.fetch_message(last_embed_id)
                # Zawsze edytuj istniejącą wiadomość, nawet jeśli zmienia się ikona
                await message.edit(embed=embed)
                logger.discord_message("edited", last_embed_id, channel=channel.name)
                save_bot_data()  # Zapisz dane po aktualizacji
                return
            except discord.NotFound:
                logger.warning("Discord", f"Wiadomość o ID {last_embed_id} nie została znaleziona. Wysyłam nową.",
                               log_type="DISCORD")
                last_embed_id = None
            except Exception as e:
                logger.error("Discord", f"Błąd podczas edycji wiadomości: {e}.", log_type="DISCORD")
                last_embed_id = None

        # Jeśli doszliśmy tutaj, musimy wysłać nową wiadomość (np. pierwsza lub poprzednia usunięta)
        # Wysyłamy zawsze bez załącznika ikony, aby uniknąć usuwania wiadomości w przyszłości
        message = await channel.send(embed=embed)
        logger.discord_message("sent", message.id, channel=channel.name)
        last_embed_id = message.id

        # Zapisz dane po wysłaniu nowej wiadomości
        save_bot_data()

    except Exception as e:
        logger.critical("Tasks", f"Wystąpił błąd w funkcji check_server: {e}", log_type="BOT")


# Definicja komendy slash (/ski)
@tree.command(
    name="ski",
    description="Sprawdza aktualny stan serwera Minecraft"
)
async def mc_server_command(interaction: discord.Interaction):
    """
    Komenda slash do ręcznego sprawdzenia stanu serwera.

    Pozwala użytkownikom na ręczne wywołanie sprawdzenia stanu serwera
    bez czekania na automatyczne odświeżenie co 5 minut.

    Args:
        interaction (discord.Interaction): Obiekt interakcji z Discord
    """
    logger.info("Commands", f"Użytkownik {interaction.user.name} użył komendy /ski", log_type="BOT")

    # Sprawdź, czy jesteśmy na właściwym kanale
    if interaction.channel_id != CHANNEL_ID:
        logger.warning("Commands", f"Komenda wywołana na niewłaściwym kanale: {interaction.channel.name}",
                       log_type="BOT")
        await interaction.response.send_message(f"Ta komenda działa tylko na kanale <#{CHANNEL_ID}>", ephemeral=True)
        return

    # Odpowiedz na interakcję, by uniknąć timeoutu
    await interaction.response.defer(thinking=True)

    # Wywołaj sprawdzenie serwera
    await check_server()

    # Odpowiedz użytkownikowi
    await interaction.followup.send("Zaktualizowano status serwera!", ephemeral=True)
    logger.info("Commands", "Wykonano ręczne sprawdzenie serwera", log_type="BOT")


# Uruchom bota
if __name__ == "__main__":
    # Upewnij się, że katalog logów istnieje
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    logger.bot_status("connecting")
    try:
        client.run(DISCORD_TOKEN)
    except Exception as e:
        logger.bot_status("error", str(e))
