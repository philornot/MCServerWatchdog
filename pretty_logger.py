import datetime
import json
import os
import sys

import pytz
import structlog
from colorama import init, Fore, Back, Style
from rich.console import Console
from rich.traceback import install as install_rich_traceback

# Inicjalizacja colorama i rich
init(autoreset=True)
console = Console()
install_rich_traceback()


class PrettyLogger:
    """
    Piękny logger wykorzystujący structlog z kolorowym formatowaniem konsoli i czystymi plikami logów.
    """

    # Poziomy logowania
    LEVELS = {
        "TRACE": {"color": Fore.MAGENTA, "symbol": "🔬", "level": 9},  # Zmienione z 5 na 9
        "DEBUG": {"color": Fore.CYAN, "symbol": "🔍", "level": 10},
        "INFO": {"color": Fore.GREEN, "symbol": "ℹ️", "level": 20},
        "WARNING": {"color": Fore.YELLOW, "symbol": "⚠️", "level": 30},
        "ERROR": {"color": Fore.RED, "symbol": "❌", "level": 40},
        "CRITICAL": {"color": Fore.RED + Back.WHITE, "symbol": "🔥", "level": 50},
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

    # W pliku pretty_logger.py, w metodzie __init__, dodaj po importach ale przed konfiguracją:

    def __init__(self, log_file=None, console_level="INFO", file_level="DEBUG", timezone="Europe/Warsaw",
                 max_json_length=500, trim_lists=True, verbose_api=False):
        """
        Inicjalizacja loggera z użyciem structlog.

        :param log_file: Ścieżka do pliku z logami. Jeśli None, logi nie będą zapisywane do pliku.
        :param console_level: Poziom logowania dla konsoli.
        :param file_level: Poziom logowania dla pliku.
        :param timezone: Strefa czasowa do formatowania czasu.
        :param max_json_length: Maksymalna długość logowanych JSONów przed ich przycięciem
        :param trim_lists: Czy przycinać długie listy w logach
        :param verbose_api: Czy logować pełne odpowiedzi API (True) czy tylko najważniejsze pola (False)
        """
        self.timezone = pytz.timezone(timezone)
        self.console_level = console_level
        self.file_level = file_level
        self.log_file = log_file
        self.max_json_length = max_json_length
        self.trim_lists = trim_lists
        self.verbose_api = verbose_api

        # Zarejestruj custom poziom TRACE w systemie logowania Pythona
        import logging
        TRACE_LEVEL = 5
        logging.addLevelName(TRACE_LEVEL, "TRACE")

        # Dodaj metodę trace do klasy Logger
        def trace_method(self, message, *args, **kwargs):
            if self.isEnabledFor(TRACE_LEVEL):
                self._log(TRACE_LEVEL, message, args, **kwargs)

        logging.Logger.trace = trace_method

        # Przygotuj procesory dla structlog
        processors = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            self._add_timestamp,
            self._process_event,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]

        # Konfiguracja structlog
        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Pobierz logger
        self.logger = structlog.get_logger("MCServerWatchDog")

        # Konfiguracja handlerów
        stdlib_logger = logging.getLogger("MCServerWatchDog")
        stdlib_logger.setLevel(self.LEVELS[file_level]["level"] if log_file else self.LEVELS[console_level]["level"])
        stdlib_logger.handlers = []

        # Handler konsoli
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.LEVELS[console_level]["level"])
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=self._console_renderer,
            foreign_pre_chain=processors[:-1],
        )
        console_handler.setFormatter(console_formatter)
        stdlib_logger.addHandler(console_handler)

        # Handler pliku (jeśli podano)
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(self.LEVELS[file_level]["level"])
            file_formatter = structlog.stdlib.ProcessorFormatter(
                processor=self._file_renderer,
                foreign_pre_chain=processors[:-1],
            )
            file_handler.setFormatter(file_formatter)
            stdlib_logger.addHandler(file_handler)

        self.info("Logger", "Inicjalizacja loggera zakończona pomyślnie", log_type="CONFIG")

    def _add_timestamp(self, logger, method_name, event_dict):
        """Dodaje timestamp do event_dict."""
        event_dict["timestamp"] = datetime.datetime.now(self.timezone)
        return event_dict

    def _process_event(self, logger, method_name, event_dict):
        """Przetwarza event przed renderowaniem."""
        # Przetwórz specjalne pola
        if "response" in event_dict and not self.verbose_api:
            event_dict["response"] = self._format_api_response(event_dict["response"])

        # Przytnij długie struktury danych
        for key, value in list(event_dict.items()):
            if key not in ["event", "timestamp", "level", "logger", "module", "log_type"]:
                if isinstance(value, (dict, list)):
                    event_dict[key] = self._smart_trim(value)

        return event_dict

    def _console_renderer(self, logger, name, event_dict):
        """Renderuje log dla konsoli z kolorami."""
        timestamp = event_dict.pop("timestamp", datetime.datetime.now(self.timezone))
        level = event_dict.pop("level", "INFO").upper()
        module = event_dict.pop("module", "Unknown")
        log_type = event_dict.pop("log_type", None)
        message = event_dict.pop("event", "")

        # Pobierz informacje o poziomie
        level_info = self.LEVELS.get(level, self.LEVELS["INFO"])

        # Formatowanie czasu
        time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Buduj wiadomość
        formatted = f"{level_info['color']}[{time_str}] {level_info['symbol']} [{level}]"

        # Dodaj typ logu
        if log_type and log_type in self.TYPES:
            type_info = self.TYPES[log_type]
            formatted += f" {type_info['color']}{type_info['symbol']} [{log_type}]"

        # Dodaj moduł i wiadomość
        formatted += f" {Style.BRIGHT}{Fore.WHITE}[{module}]{Style.RESET_ALL} {message}"

        # Dodaj dodatkowe dane
        if event_dict:
            formatted += f"\n{self._format_extra_data(event_dict, colored=True)}"

        return formatted

    def _file_renderer(self, logger, name, event_dict):
        """Renderuje log dla pliku bez kolorów."""
        timestamp = event_dict.pop("timestamp", datetime.datetime.now(self.timezone))
        level = event_dict.pop("level", "INFO").upper()
        module = event_dict.pop("module", "Unknown")
        log_type = event_dict.pop("log_type", None)
        message = event_dict.pop("event", "")

        # Pobierz informacje o poziomie
        level_info = self.LEVELS.get(level, self.LEVELS["INFO"])

        # Formatowanie czasu
        time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Buduj wiadomość
        formatted = f"[{time_str}] {level_info['symbol']} [{level}]"

        # Dodaj typ logu
        if log_type and log_type in self.TYPES:
            type_info = self.TYPES[log_type]
            formatted += f" {type_info['symbol']} [{log_type}]"

        # Dodaj moduł i wiadomość
        formatted += f" [{module}] {message}"

        # Dodaj dodatkowe dane
        if event_dict:
            formatted += f"\n{self._format_extra_data(event_dict, colored=False)}"

        return formatted

    def _format_extra_data(self, data, colored=True):
        """Formatuje dodatkowe dane."""
        lines = []
        for key, value in data.items():
            prefix = f"{Fore.CYAN}[DATA] {key}:" if colored else f"[DATA] {key}:"

            if isinstance(value, (dict, list)):
                json_str = self._log_json(value)
                lines.append(f"{prefix}\n{json_str}")
            else:
                lines.append(f"{prefix} {value}")

        return "\n".join(lines)

    def _smart_trim(self, data, max_depth=2, current_depth=0):
        """Inteligentnie przycina złożone struktury danych."""
        if current_depth >= max_depth:
            if isinstance(data, dict) and len(data) > 3:
                return {k: "..." for k, v in list(data.items())[:3]}
            elif isinstance(data, list) and len(data) > 3:
                return data[:3] + [f"... (i {len(data) - 3} więcej elementów)"]
            else:
                return data

        if isinstance(data, dict):
            return {k: self._smart_trim(v, max_depth, current_depth + 1) for k, v in data.items()}
        elif isinstance(data, list) and self.trim_lists and len(data) > 5:
            return [self._smart_trim(x, max_depth, current_depth + 1) for x in data[:5]] + \
                [f"... (i {len(data) - 5} więcej elementów)"]
        elif isinstance(data, list):
            return [self._smart_trim(x, max_depth, current_depth + 1) for x in data]
        else:
            return data

    def _format_api_response(self, data):
        """Inteligentnie przetwarza odpowiedź API."""
        if not isinstance(data, dict):
            return data

        important_data = {}

        # Zapisujemy najważniejsze pola
        for key in ["online", "version", "hostname", "error"]:
            if key in data:
                important_data[key] = data[key]

        # Dane o graczach
        if "players" in data:
            important_data["players"] = {
                "online": data["players"].get("online", 0),
                "max": data["players"].get("max", 0)
            }
            if "list" in data["players"] and data["players"]["list"]:
                important_data["players"]["list"] = data["players"]["list"]

        # MOTD
        if "motd" in data and "clean" in data["motd"]:
            important_data["motd"] = {"clean": data["motd"]["clean"]}

        # Debug info
        if "debug" in data and "error" in data["debug"]:
            important_data["debug"] = {"error": data["debug"]["error"]}

        return important_data

    def _log_json(self, data, max_length=None):
        """Formatuje dane jako JSON."""
        if max_length is None:
            max_length = self.max_json_length

        try:
            json_text = json.dumps(data, indent=2, ensure_ascii=False)

            if len(json_text) > max_length:
                half_length = max_length // 2 - 10
                return (json_text[:half_length] +
                        f"\n...\n[skrócono {len(json_text) - max_length} znaków]\n..." +
                        json_text[-half_length:])
            return json_text
        except Exception as e:
            return f"<błąd formatowania JSON: {e}>"

    # Metody logowania
    def trace(self, module, message, log_type=None, **kwargs):
        """Log najdrobniejszych szczegółów (poziom TRACE)."""
        self.logger.debug(f"[TRACE] {message}", module=module, log_type=log_type, **kwargs)

    def debug(self, module, message, log_type=None, **kwargs):
        """Log debugowania."""
        self.logger.debug(message, module=module, log_type=log_type, **kwargs)

    def info(self, module, message, log_type=None, **kwargs):
        """Log informacyjny."""
        self.logger.info(message, module=module, log_type=log_type, **kwargs)

    def warning(self, module, message, log_type=None, **kwargs):
        """Log ostrzeżenia."""
        self.logger.warning(message, module=module, log_type=log_type, **kwargs)

    def error(self, module, message, log_type=None, **kwargs):
        """Log błędu."""
        self.logger.error(message, module=module, log_type=log_type, **kwargs)

    def critical(self, module, message, log_type=None, **kwargs):
        """Log krytyczny."""
        self.logger.critical(message, module=module, log_type=log_type, **kwargs)

    # Metody specjalne (zachowane dla kompatybilności)
    def server_status(self, status, server_data):
        """Specjalny log dla statusu serwera."""
        if status:
            players = server_data.get("players", {})
            player_count = players.get("online", 0)
            max_players = players.get("max", 0)
            player_list = players.get("list", [])

            self.info(
                "ServerStatus",
                f"Serwer ONLINE - Gracze: {player_count}/{max_players}",
                log_type="SERVER",
                players=player_list
            )
        else:
            self.warning(
                "ServerStatus",
                "Serwer OFFLINE",
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
            self.debug("API", f"Żądanie do {url} zakończone kodem {status}", log_type="API")
            if response:
                self.trace("API", "Szczegóły odpowiedzi API", log_type="API", response=response)

    def player_activity(self, player, status, last_seen=None):
        """Log aktywności gracza."""
        if status == "online":
            self.info("Players", f"Gracz {player} jest online", log_type="DATA")
        elif status == "offline":
            self.info("Players", f"Gracz {player} jest offline (ostatnio widziany: {last_seen})", log_type="DATA")
