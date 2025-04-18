import datetime
import os
from colorama import init, Fore, Back, Style
import json
import logging
import pytz

# Inicjalizacja colorama
init(autoreset=True)


class PrettyLogger:
    """
    Piękny logger z kolorowym formatowaniem i wieloma funkcjami ułatwiającymi debugowanie.
    """

    # Poziomy logowania
    LEVELS = {
        "DEBUG": {"color": Fore.CYAN, "symbol": "🔍", "level": logging.DEBUG},
        "INFO": {"color": Fore.GREEN, "symbol": "ℹ️", "level": logging.INFO},
        "WARNING": {"color": Fore.YELLOW, "symbol": "⚠️", "level": logging.WARNING},
        "ERROR": {"color": Fore.RED, "symbol": "❌", "level": logging.ERROR},
        "CRITICAL": {"color": Fore.RED + Back.WHITE, "symbol": "🔥", "level": logging.CRITICAL},
    }

    # Specjalne typy logów
    TYPES = {
        "SERVER": {"color": Fore.MAGENTA, "symbol": "🖥️"},
        "BOT": {"color": Fore.BLUE, "symbol": "🤖"},
        "DISCORD": {"color": Fore.LIGHTBLUE_EX, "symbol": "💬"},
        "DATA": {"color": Fore.YELLOW, "symbol": "📊"},
        "CONFIG": {"color": Fore.GREEN, "symbol": "⚙️"},
        "API": {"color": Fore.CYAN, "symbol": "🌐"},
    }

    def __init__(self, log_file=None, console_level="DEBUG", file_level="INFO", timezone="Europe/Warsaw"):
        """
        Inicjalizacja loggera.

        :param log_file: Ścieżka do pliku z logami. Jeśli None, logi nie będą zapisywane do pliku.
        :param console_level: Poziom logowania dla konsoli.
        :param file_level: Poziom logowania dla pliku.
        :param timezone: Strefa czasowa do formatowania czasu.
        """
        self.timezone = pytz.timezone(timezone)
        self.console_level = console_level
        self.file_level = file_level
        self.log_file = log_file

        # Konfiguracja loggera
        self.logger = logging.getLogger("MCServerWatchDog")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []  # Usuń wszystkie handlery

        # Dodaj handler konsoli
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.LEVELS[console_level]["level"])
        self.logger.addHandler(console_handler)

        # Dodaj handler pliku, jeśli podano
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(self.LEVELS[file_level]["level"])
            self.logger.addHandler(file_handler)

        self.info("Logger", "Inicjalizacja loggera zakończona pomyślnie", log_type="CONFIG")

    def _format_message(self, level, module, message, log_type=None):
        """Formatuje wiadomość logu."""
        now = datetime.datetime.now(self.timezone)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        level_info = self.LEVELS[level]

        # Podstawowe formatowanie
        formatted = f"{level_info['color']}[{time_str}] {level_info['symbol']} [{level}]"

        # Dodaj typ logu, jeśli podano
        if log_type and log_type in self.TYPES:
            type_info = self.TYPES[log_type]
            formatted += f" {type_info['color']}{type_info['symbol']} [{log_type}]"

        # Dodaj moduł i wiadomość
        formatted += f" {Style.BRIGHT}{Fore.WHITE}[{module}]{Style.RESET_ALL} {message}"

        return formatted

    def _log(self, level, module, message, log_type=None, **kwargs):
        """Zapisuje log z określonym poziomem."""
        formatted = self._format_message(level, module, message, log_type)

        # Zapisz do loggera z odpowiednim poziomem
        getattr(self.logger, level.lower())(formatted)

        # Jeśli są dodatkowe dane, wypisz je ładnie
        if kwargs:
            self._log_data(level, **kwargs)

    def _log_data(self, level, **kwargs):
        """Loguje dodatkowe dane jako JSON."""
        for key, value in kwargs.items():
            if value is not None:
                try:
                    # Jeśli to słownik lub lista, wydrukuj jako JSON
                    if isinstance(value, (dict, list)):
                        formatted_json = json.dumps(value, indent=2, ensure_ascii=False)
                        self.logger.debug(f"{Fore.CYAN}[DATA] {key}:\n{formatted_json}")
                    else:
                        self.logger.debug(f"{Fore.CYAN}[DATA] {key}: {value}")
                except Exception as e:
                    self.logger.error(f"Błąd podczas logowania danych: {e}")

    def debug(self, module, message, log_type=None, **kwargs):
        """Log debugowania."""
        self._log("DEBUG", module, message, log_type, **kwargs)

    def info(self, module, message, log_type=None, **kwargs):
        """Log informacyjny."""
        self._log("INFO", module, message, log_type, **kwargs)

    def warning(self, module, message, log_type=None, **kwargs):
        """Log ostrzeżenia."""
        self._log("WARNING", module, message, log_type, **kwargs)

    def error(self, module, message, log_type=None, **kwargs):
        """Log błędu."""
        self._log("ERROR", module, message, log_type, **kwargs)

    def critical(self, module, message, log_type=None, **kwargs):
        """Log krytyczny."""
        self._log("CRITICAL", module, message, log_type, **kwargs)

    def server_status(self, status, server_data):
        """Specjalny log dla statusu serwera."""
        if status:
            status_str = f"{Fore.GREEN}ONLINE"
            players = server_data.get("players", {})
            player_count = players.get("online", 0)
            max_players = players.get("max", 0)
            player_list = players.get("list", [])

            self.info(
                "ServerStatus",
                f"Serwer {status_str} - Gracze: {player_count}/{max_players}",
                log_type="SERVER",
                players=player_list,
                version=server_data.get("version", "Unknown"),
                server_data=server_data
            )
        else:
            status_str = f"{Fore.RED}OFFLINE"
            self.warning(
                "ServerStatus",
                f"Serwer {status_str}",
                log_type="SERVER",
                error=server_data.get("error", "Unknown error")
            )

    def bot_status(self, status, message=None):
        """Status bota Discord."""
        if status == "ready":
            self.info("DiscordBot", f"Bot uruchomiony jako {message}", log_type="BOT")
        elif status == "connecting":
            self.info("DiscordBot", "Łączenie z Discord...", log_type="BOT")
        elif status == "error":
            self.error("DiscordBot", f"Błąd bota: {message}", log_type="BOT")
        else:
            self.info("DiscordBot", message, log_type="BOT")

    def discord_message(self, action, message_id=None, content=None, channel=None):
        """Log akcji na wiadomościach Discord."""
        if action == "sent":
            self.info("Discord", f"Wysłano wiadomość (ID: {message_id}) na kanale {channel}", log_type="DISCORD")
        elif action == "edited":
            self.info("Discord", f"Zaktualizowano wiadomość (ID: {message_id}) na kanale {channel}", log_type="DISCORD")
        elif action == "deleted":
            self.info("Discord", f"Usunięto wiadomość (ID: {message_id}) z kanału {channel}", log_type="DISCORD")
        else:
            self.info("Discord", content, log_type="DISCORD")

    def api_request(self, url, response=None, status=None, error=None):
        """Log żądania API."""
        if error:
            self.error("API", f"Błąd podczas żądania do {url}: {error}", log_type="API")
        else:
            self.debug("API", f"Żądanie do {url} zakończone kodem {status}", log_type="API", response=response)

    def player_activity(self, player, status, last_seen=None):
        """Log aktywności gracza."""
        if status == "online":
            self.info("Players", f"Gracz {player} jest online", log_type="DATA")
        elif status == "offline":
            self.info("Players", f"Gracz {player} jest offline (ostatnio widziany: {last_seen})", log_type="DATA")