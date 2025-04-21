import datetime
import json
import logging
import os
import re

import pytz
from colorama import init, Fore, Back, Style

# Inicjalizacja colorama
init(autoreset=True)


class PrettyLogger:
    """
    Piękny logger z kolorowym formatowaniem konsoli i czystymi plikami logów.
    """

    # Poziomy logowania
    LEVELS = {
        "TRACE": {"color": Fore.MAGENTA, "symbol": "🔬", "level": 5},
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

    # Dodajemy poziom TRACE do biblioteki logging
    logging.addLevelName(5, "TRACE")

    class ColoredFormatter(logging.Formatter):
        """Formatter dodający kolory dla konsoli."""

        def format(self, record):
            return record.msg

    class PlainFormatter(logging.Formatter):
        """Formatter bez kolorów dla pliku."""

        def format(self, record):
            if hasattr(record, 'plain_msg'):
                return record.plain_msg
            # Usuwamy sekwencje ANSI z wiadomości
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', record.msg)

    def __init__(self, log_file=None, console_level="INFO", file_level="DEBUG", timezone="Europe/Warsaw",
                 max_json_length=500, trim_lists=True, verbose_api=False):
        """
        Inicjalizacja loggera.

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

        # Konfiguracja loggera
        self.logger = logging.getLogger("MCServerWatchDog")
        self.logger.setLevel(5)  # Najniższy poziom (TRACE)
        self.logger.handlers = []  # Usuń wszystkie handlery

        # Dodaj handler konsoli
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.LEVELS[console_level]["level"])
        console_handler.setFormatter(self.ColoredFormatter())
        self.logger.addHandler(console_handler)

        # Dodaj handler pliku, jeśli podano
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(self.LEVELS[file_level]["level"])
            file_handler.setFormatter(self.PlainFormatter())
            self.logger.addHandler(file_handler)

        self.info("Logger", "Inicjalizacja loggera zakończona pomyślnie", log_type="CONFIG")

    def _format_message(self, level, module, message, log_type=None, plain=False):
        """Formatuje wiadomość logu."""
        now = datetime.datetime.now(self.timezone)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        level_info = self.LEVELS[level]

        if plain:
            # Formatowanie bez kolorów dla plików logów
            formatted = f"[{time_str}] {level_info['symbol']} [{level}]"

            # Dodaj typ logu, jeśli podano
            if log_type and log_type in self.TYPES:
                type_info = self.TYPES[log_type]
                formatted += f" {type_info['symbol']} [{log_type}]"

            # Dodaj moduł i wiadomość
            formatted += f" [{module}] {message}"
        else:
            # Formatowanie z kolorami dla konsoli
            formatted = f"{level_info['color']}[{time_str}] {level_info['symbol']} [{level}]"

            # Dodaj typ logu, jeśli podano
            if log_type and log_type in self.TYPES:
                type_info = self.TYPES[log_type]
                formatted += f" {type_info['color']}{type_info['symbol']} [{log_type}]"

            # Dodaj moduł i wiadomość
            formatted += f" {Style.BRIGHT}{Fore.WHITE}[{module}]{Style.RESET_ALL} {message}"

        return formatted

    def _smart_trim(self, data, max_depth=2, current_depth=0):
        """
        Inteligentnie przycina złożone struktury danych, zachowując czytelność.
        """
        if current_depth >= max_depth:
            if isinstance(data, dict) and len(data) > 3:
                return {k: "..." for k, v in list(data.items())[:3]}
            elif isinstance(data, list) and len(data) > 3:
                return data[:3] + ["... (i {} więcej elementów)".format(len(data) - 3)]
            else:
                return data

        if isinstance(data, dict):
            return {k: self._smart_trim(v, max_depth, current_depth + 1) for k, v in data.items()}
        elif isinstance(data, list) and self.trim_lists and len(data) > 5:
            return [self._smart_trim(x, max_depth, current_depth + 1) for x in data[:5]] + \
                ["... (i {} więcej elementów)".format(len(data) - 5)]
        elif isinstance(data, list):
            return [self._smart_trim(x, max_depth, current_depth + 1) for x in data]
        else:
            return data

    def _format_api_response(self, data):
        """
        Inteligentnie przetwarza odpowiedź API, pozostawiając tylko najważniejsze informacje.
        """
        if not self.verbose_api:
            # Jeśli nie chcemy pełnych odpowiedzi, wyciągamy kluczowe informacje
            important_data = {}

            # Zapisujemy najważniejsze pola
            for key in ["online", "version", "hostname"]:
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

            # MOTD jest ważne dla wykrywania stanu
            if "motd" in data and "clean" in data["motd"]:
                important_data["motd"] = {"clean": data["motd"]["clean"]}

            # Błędy zawsze zachowujemy
            if "error" in data:
                important_data["error"] = data["error"]

            if "debug" in data and "error" in data["debug"]:
                important_data["debug"] = {"error": data["debug"]["error"]}

            return important_data
        else:
            # Jeśli chcemy pełne odpowiedzi, inteligentnie przycinamy
            return self._smart_trim(data)

    def _log_json(self, data, max_length=None):
        """
        Inteligentne logowanie danych JSON z ograniczeniem długości.
        """
        if max_length is None:
            max_length = self.max_json_length

        try:
            json_text = json.dumps(data, indent=2, ensure_ascii=False)

            if len(json_text) > max_length:
                # Jeśli tekst jest za długi, pokazujemy początek i koniec
                half_length = max_length // 2 - 10
                return json_text[:half_length] + "\n...\n[skrócono " + str(
                    len(json_text) - max_length) + " znaków]\n..." + json_text[-half_length:]
            return json_text
        except Exception as e:
            return f"<błąd formatowania JSON: {e}>"

    def _log(self, level, module, message, log_type=None, **kwargs):
        """Zapisuje log z określonym poziomem."""
        # Tworzenie dwóch formatów wiadomości - z kolorami i bez kolorów
        formatted = self._format_message(level, module, message, log_type, plain=False)
        plain_formatted = self._format_message(level, module, message, log_type, plain=True)

        # Niestandardowa obsługa log recordu, aby przechować obie wersje wiadomości
        log_record = logging.LogRecord(
            name=self.logger.name,
            level=self.LEVELS[level]["level"] if level != "TRACE" else 5,
            pathname="",
            lineno=0,
            msg=formatted,
            args=(),
            exc_info=None
        )
        # Dodajemy plain_msg jako atrybut, który zostanie użyty przez PlainFormatter
        log_record.plain_msg = plain_formatted

        # Przekazanie rekordu do wszystkich handlerów
        for handler in self.logger.handlers:
            if handler.level <= log_record.levelno:
                handler.handle(log_record)

        # Jeśli są dodatkowe dane, wypisz je ładnie
        if kwargs:
            filtered_kwargs = {}

            # Przetwarzanie specjalnych pól
            for key, value in kwargs.items():
                if key == "response" and not self.verbose_api:
                    # Dla odpowiedzi API stosujemy specjalne przetwarzanie
                    filtered_kwargs[key] = self._format_api_response(value)
                elif isinstance(value, (dict, list)):
                    # Dla złożonych struktur stosujemy inteligentne przycinanie
                    filtered_kwargs[key] = self._smart_trim(value)
                else:
                    # Wartości proste pozostawiamy bez zmian
                    filtered_kwargs[key] = value

            # Logujemy przetworzone dane
            self._log_data(level, **filtered_kwargs)

    def _log_data(self, level, **kwargs):
        """Loguje dodatkowe dane jako JSON."""
        log_level = 5 if level == "TRACE" else self.LEVELS[level]["level"]

        for key, value in kwargs.items():
            if value is not None:
                try:
                    # Przygotuj tekst dla konsoli (kolorowy)
                    console_prefix = f"{Fore.CYAN}[DATA] {key}:"

                    # Przygotuj tekst dla pliku (bez kolorów)
                    file_prefix = f"[DATA] {key}:"

                    # Logowanie w zależności od typu danych
                    if isinstance(value, (dict, list)):
                        formatted_json = self._log_json(value)

                        # Tworzenie rekordów logów z różnymi formatami dla konsoli i pliku
                        console_record = logging.LogRecord(
                            name=self.logger.name,
                            level=log_level,
                            pathname="",
                            lineno=0,
                            msg=f"{console_prefix}\n{formatted_json}",
                            args=(),
                            exc_info=None
                        )
                        console_record.plain_msg = f"{file_prefix}\n{formatted_json}"
                    else:
                        # Dla prostych wartości
                        console_record = logging.LogRecord(
                            name=self.logger.name,
                            level=log_level,
                            pathname="",
                            lineno=0,
                            msg=f"{console_prefix} {value}",
                            args=(),
                            exc_info=None
                        )
                        console_record.plain_msg = f"{file_prefix} {value}"

                    # Przekazanie rekordów do handlerów
                    for handler in self.logger.handlers:
                        if handler.level <= log_level:
                            handler.handle(console_record)

                except Exception as e:
                    self.logger.error(f"Błąd podczas logowania danych: {e}")

    def trace(self, module, message, log_type=None, **kwargs):
        """Log najdrobniejszych szczegółów (poziom TRACE)."""
        self._log("TRACE", module, message, log_type, **kwargs)

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
        """
        Specjalny log dla statusu serwera.

        Tworzy log statusu serwera Minecraft bez używania kolorowania ANSI
        w treści wiadomości, co zapewnia czystość plików logów.

        Args:
            status (bool): True jeśli serwer jest online, False w przeciwnym przypadku
            server_data (dict): Dane serwera z API
        """
        if status:
            # Bez kolorowania w samej treści wiadomości
            status_text = "ONLINE"
            players = server_data.get("players", {})
            player_count = players.get("online", 0)
            max_players = players.get("max", 0)
            player_list = players.get("list", [])

            # Używamy INFO zamiast DEBUG dla ważnych informacji
            self.info(
                "ServerStatus",
                f"Serwer {status_text} - Gracze: {player_count}/{max_players}",
                log_type="SERVER",
                players=player_list
            )

            # Szczegóły serwera logujemy na poziomie DEBUG lub TRACE
            if self.verbose_api:
                self.debug(
                    "ServerDetails",
                    f"Szczegółowe informacje o serwerze",
                    log_type="SERVER",
                    version=server_data.get("version", "Unknown"),
                    server_data=server_data
                )
            else:
                self.trace(
                    "ServerDetails",
                    f"Szczegółowe informacje o serwerze",
                    log_type="SERVER",
                    version=server_data.get("version", "Unknown"),
                    server_data=server_data
                )
        else:
            status_text = "OFFLINE"
            self.warning(
                "ServerStatus",
                f"Serwer {status_text}",
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
            # Pełną odpowiedź API logujemy na poziomie TRACE, a na DEBUG tylko podstawowe informacje
            self.debug("API", f"Żądanie do {url} zakończone kodem {status}", log_type="API")
            if response:
                self.trace("API", f"Szczegóły odpowiedzi API", log_type="API", response=response)

    def player_activity(self, player, status, last_seen=None):
        """Log aktywności gracza."""
        if status == "online":
            self.info("Players", f"Gracz {player} jest online", log_type="DATA")
        elif status == "offline":
            self.info("Players", f"Gracz {player} jest offline (ostatnio widziany: {last_seen})", log_type="DATA")
