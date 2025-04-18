import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import json
import datetime
import pytz
import os
import pickle
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

# Inicjalizacja bota
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)  # Command tree for slash commands

# ID ostatnio wysłanego embeda
last_embed_id = None

# Format czasu warszawskiego
warsaw_tz = pytz.timezone('Europe/Warsaw')


def ensure_data_dir():
    """Upewnia się, że katalog danych istnieje."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)


def save_bot_data():
    """Zapisuje dane bota do pliku."""
    ensure_data_dir()
    data = {
        "last_embed_id": last_embed_id,
        "last_seen": last_seen
    }
    try:
        with open(DATA_FILE, "wb") as f:
            pickle.dump(data, f)
        logger.debug("DataStorage", f"Zapisano dane bota do {DATA_FILE}", log_type="CONFIG")
    except Exception as e:
        logger.error("DataStorage", f"Błąd podczas zapisywania danych: {e}", log_type="CONFIG")


def load_bot_data():
    """Ładuje dane bota z pliku."""
    global last_embed_id, last_seen
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "rb") as f:
                data = pickle.load(f)
                last_embed_id = data.get("last_embed_id")
                stored_last_seen = data.get("last_seen", {})
                if stored_last_seen:
                    last_seen = stored_last_seen
                logger.debug("DataStorage", f"Załadowano dane bota z {DATA_FILE}",
                             last_embed_id=last_embed_id,
                             players_count=len(last_seen),
                             log_type="CONFIG")
        else:
            logger.debug("DataStorage", f"Nie znaleziono pliku danych {DATA_FILE}", log_type="CONFIG")
    except Exception as e:
        logger.error("DataStorage", f"Błąd podczas ładowania danych: {e}", log_type="CONFIG")


def get_warsaw_time():
    """Zwraca aktualny czas w strefie czasowej Warszawy."""
    return datetime.datetime.now(warsaw_tz)


def format_time(dt):
    """Formatuje datę i czas w czytelny sposób."""
    return dt.strftime("%d-%m-%Y %H:%M:%S")


async def check_minecraft_server():
    """Sprawdza status serwera Minecraft i zwraca dane w formie słownika."""
    api_url = f"https://api.mcsrvstat.us/2/{MC_SERVER_ADDRESS}:{MC_SERVER_PORT}"

    try:
        logger.debug("ServerCheck", f"Sprawdzanie stanu serwera {MC_SERVER_ADDRESS}:{MC_SERVER_PORT}", log_type="API")

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.api_request(api_url, response=data, status=response.status)

                    # Logowanie szczegółowych informacji o serwerze
                    if data.get("online", False):
                        logger.server_status(True, data)
                    else:
                        logger.server_status(False, data)

                    return data
                else:
                    error_msg = f"API Error: {response.status}"
                    logger.api_request(api_url, status=response.status, error=error_msg)
                    return {"online": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        logger.api_request(api_url, error=error_msg)
        return {"online": False, "error": error_msg}


async def update_last_seen(online_players):
    """Aktualizuje listę ostatnio widzianych graczy."""
    current_time = get_warsaw_time()

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
    """Tworzy embed z informacjami o serwerze Minecraft."""
    current_time = get_warsaw_time()

    # Dodane logowanie dla debugowania danych serwera
    logger.debug("EmbedCreation", "Rozpoczęcie tworzenia embeda",
                 raw_server_data=server_data)

    # Dodane dodatkowe logowanie dla graczy
    player_list = server_data.get("players", {}).get("list", [])
    logger.debug("EmbedCreation", f"Lista graczy z API: {player_list}",
                 player_count=len(player_list),
                 player_data=server_data.get("players", {}))

    # Ustawienie koloru embeda
    if server_data.get("online", False):
        if server_data.get("players", {}).get("online", 0) > 0:
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
    status = "ONLINE" if server_data.get("online", False) else "OFFLINE"
    embed.add_field(name="Status", value=status, inline=False)

    # Jeśli serwer jest online, dodaj więcej informacji
    if server_data.get("online", False):
        # Wersja
        version = server_data.get("version", "Nieznana")
        embed.add_field(name="Wersja", value=version, inline=True)

        # Liczba graczy
        players_online = server_data.get("players", {}).get("online", 0)
        players_max = server_data.get("players", {}).get("max", 0)
        embed.add_field(name="Gracze", value=f"{players_online}/{players_max}", inline=True)

        # Lista graczy
        if player_list:
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

                embed.add_field(name=field_name, value=f"```{first_part}... i {player_count - 5} więcej```",
                                inline=False)
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
                if player not in player_list:  # Tylko gracze, którzy nie są obecnie online
                    last_seen_text += f"{player}: {format_time(last_time)}\n"
                    offline_players.append(f"{player}: {format_time(last_time)}")

            if last_seen_text:
                embed.add_field(name="Ostatnio widziani", value=f"```{last_seen_text}```", inline=False)
                logger.debug("Embed", "Dodano listę ostatnio widzianych graczy", offline_players=offline_players)

    # Stopka z czasem ostatniej aktualizacji
    embed.set_footer(text=f"Ostatnia aktualizacja: {format_time(current_time)}")
    logger.debug("Embed", f"Utworzono embed z czasem aktualizacji: {format_time(current_time)}")

    return embed


async def find_and_delete_previous_message():
    """Znajduje i usuwa poprzednią wiadomość bota na kanale."""
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
                logger.info("Cleanup", f"Usunięto poprzednią wiadomość (ID: {last_embed_id})", log_type="BOT")
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
    """Funkcja wywoływana po poprawnym uruchomieniu bota."""
    logger.bot_status("ready", client.user)

    # Ładuj zapisane dane
    load_bot_data()

    # Sprawdź, czy kanał istnieje
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error("DiscordBot", f"Nie znaleziono kanału o ID {CHANNEL_ID}", log_type="BOT")
        return

    logger.info("DiscordBot", f"Połączono z kanałem '{channel.name}' (ID: {CHANNEL_ID})", log_type="BOT")

    # Usuń poprzednią wiadomość
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
    """Zadanie cyklicznie sprawdzające stan serwera i aktualizujące informacje."""
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

        # Jeśli istnieje już embed, spróbuj go zaktualizować
        if last_embed_id:
            try:
                message = await channel.fetch_message(last_embed_id)
                await message.edit(embed=embed)
                logger.discord_message("edited", last_embed_id, channel=channel.name)
                return
            except discord.NotFound:
                logger.warning("Discord", f"Wiadomość o ID {last_embed_id} nie została znaleziona. Wysyłam nową.",
                               log_type="DISCORD")
                last_embed_id = None
            except Exception as e:
                logger.error("Discord", f"Błąd podczas edycji wiadomości: {e}.", log_type="DISCORD")
                last_embed_id = None

        # Jeśli nie ma poprzedniego embeda lub wystąpił błąd, wyślij nowy
        message = await channel.send(embed=embed)
        last_embed_id = message.id
        logger.discord_message("sent", last_embed_id, channel=channel.name)

        # Zapisz dane po wysłaniu nowej wiadomości
        save_bot_data()

    except Exception as e:
        logger.critical("Tasks", f"Wystąpił błąd w funkcji check_server: {e}", log_type="BOT")


# Definicja komendy slash (/mcsv)
@tree.command(
    name="mcsv",
    description="Sprawdza aktualny stan serwera Minecraft"
)
async def mc_server_command(interaction: discord.Interaction):
    """Komenda slash do ręcznego sprawdzenia stanu serwera."""
    logger.info("Commands", f"Użytkownik {interaction.user.name} użył komendy /mcsv", log_type="BOT")

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