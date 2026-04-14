import locale
import json
import os
import re
import shutil
import subprocess
import sys

from contextlib import contextmanager
from datetime import datetime
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:
    requests = None

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:
    def _strip_markup(value):
        if not isinstance(value, str):
            return str(value)
        return re.sub(r"\[[^\]]+\]", "", value)


    class Group:
        def __init__(self, *items):
            self.items = items

        def __str__(self):
            return "\n".join(_strip_markup(item) for item in self.items)


    class Panel:
        def __init__(self, renderable, **kwargs):
            self.renderable = renderable

        def __str__(self):
            return _strip_markup(self.renderable)


    class Table:
        def __init__(self, title=None, **kwargs):
            self.title = title
            self.rows = []

        def add_column(self, *args, **kwargs):
            return None

        def add_row(self, *row):
            self.rows.append(row)

        def __str__(self):
            lines = []
            if self.title:
                lines.append(_strip_markup(self.title))
            lines.extend(" | ".join(_strip_markup(cell) for cell in row) for row in self.rows)
            return "\n".join(lines)


    class Live:
        def __init__(self, **kwargs):
            self.last_renderable = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, renderable):
            self.last_renderable = renderable
            print(_strip_markup(str(renderable)))


    class SpinnerColumn:
        pass


    class TextColumn:
        def __init__(self, *args, **kwargs):
            pass


    class Progress:
        def __init__(self, *args, **kwargs):
            self.last_description = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, description, total=None):
            self.last_description = description
            print(_strip_markup(description))
            return 1

        def update(self, task_id, description=None):
            if description and description != self.last_description:
                self.last_description = description
                print(_strip_markup(description))


    class Prompt:
        @staticmethod
        def ask(message, choices=None, default=None, show_choices=True, **kwargs):
            suffix = ""
            if choices and show_choices:
                suffix = f" ({'/'.join(choices)})"
            if default is not None:
                suffix = f"{suffix} [{default}]"
            value = input(f"{_strip_markup(message)}{suffix}: ").strip()
            if not value and default is not None:
                value = str(default)
            if choices and value not in choices:
                raise ValueError(f"Ожидается одно из значений: {', '.join(choices)}")
            return value


    class Confirm:
        @staticmethod
        def ask(message, default=False, **kwargs):
            prompt = "Y/n" if default else "y/N"
            value = input(f"{_strip_markup(message)} [{prompt}]: ").strip().lower()
            if not value:
                return default
            return value in {"y", "yes", "1", "true"}


    class Console:
        def print(self, *args, **kwargs):
            print(*(_strip_markup(str(arg)) for arg in args))

        def log(self, *args, **kwargs):
            self.print(*args)

        @contextmanager
        def status(self, message):
            self.print(message)
            yield


def ensure_utf8_locale():
    try:
        current_locale = locale.getlocale()
        if current_locale and current_locale[1] == "UTF-8":
            return
    except Exception:
        pass

    console.print("[yellow]⏳ Проверка и установка локали UTF-8...[/yellow]")

    os.environ["LC_ALL"] = "en_US.UTF-8"
    os.environ["LANG"] = "en_US.UTF-8"

    result = subprocess.run(["locale", "-a"], capture_output=True, text=True)
    if "en_US.utf8" not in result.stdout.lower():
        console.print("[blue]Добавляю локаль en_US.UTF-8 в систему...[/blue]")
        try:
            subprocess.run(["sudo", "locale-gen", "en_US.UTF-8"], check=True)
            subprocess.run(["sudo", "update-locale", "LANG=en_US.UTF-8"], check=True)
            console.print("[green]Локаль успешно установлена.[/green]")
        except Exception as e:
            console.print(f"[red]❌ Ошибка при установке локали: {e}[/red]")
    else:
        console.print("[green]Локаль UTF-8 уже доступна в системе.[/green]")


try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

console = Console()
ensure_utf8_locale()

BACK_DIR = os.path.expanduser("~/.solobot_backups")
TEMP_DIR = os.path.expanduser("~/.solobot_tmp")
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
IS_ROOT_DIR = PROJECT_DIR == "/root"
GITHUB_REPO = "https://github.com/Vladless/Solo_bot"
DEFAULT_SERVICE_NAME = "bot.service"
VENV_PYTHON = os.path.join(PROJECT_DIR, "venv", "bin", "python")


class HttpResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def http_get(url: str, *, params=None, timeout: int = 10) -> HttpResponse:
    if requests is not None:
        response = requests.get(url, params=params, timeout=timeout)
        return HttpResponse(response.status_code, response.text)

    final_url = url
    if params:
        final_url = f"{url}?{urlencode(params)}"
    request = Request(final_url, headers={"User-Agent": "SoloBot-CLI"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read().decode("utf-8"))
    except HTTPError as error:
        return HttpResponse(error.code, error.read().decode("utf-8", errors="replace"))
    except URLError:
        return HttpResponse(599, "")


def detect_service_name() -> str:
    config_path = os.path.join(PROJECT_DIR, "config.py")
    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as config_file:
                config_text = config_file.read()
            match = re.search(r"BOT_SERVICE\s*=\s*['\"]([^'\"]+)['\"]", config_text)
            if match:
                return match.group(1)
        except Exception:
            pass
    return DEFAULT_SERVICE_NAME


def refresh_service_name() -> str:
    global SERVICE_NAME, SYSTEMD_SERVICE_PATH
    SERVICE_NAME = detect_service_name()
    SYSTEMD_SERVICE_PATH = os.path.join("/etc/systemd/system", SERVICE_NAME)
    return SERVICE_NAME


SERVICE_NAME = refresh_service_name()


def is_ascii_only(value: str) -> bool:
    """Проверка, что строка содержит только ASCII."""
    return all(ord(ch) < 128 for ch in value)


def _parse_tag_version(tag_name: str) -> tuple[int, ...]:
    """Извлекает кортеж (major, minor, patch, ...) из тега для сортировки. v.5.1 -> (5, 1), v4 -> (4, 0)."""
    s = tag_name.strip().lstrip("v.")
    parts = []
    for part in re.split(r"[.\s]+", s):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def warn_english_only():
    """Предупреждение о необходимости английской раскладки."""
    console.print("[red]Обнаружен ввод с неанглийской раскладкой.[/red]")
    console.print("[yellow]Пожалуйста, переключите раскладку на ENG и введите снова.[/yellow]")


def safe_confirm(message: str, **kwargs) -> bool:
    """Безопасный Confirm.ask с защитой от русской раскладки."""
    while True:
        try:
            result = Confirm.ask(message, **kwargs)
            return result
        except UnicodeDecodeError:
            warn_english_only()


def safe_prompt(message: str, **kwargs) -> str:
    """Безопасный Prompt.ask с защитой от русской раскладки."""
    while True:
        try:
            value = Prompt.ask(message, **kwargs)
        except UnicodeDecodeError:
            warn_english_only()
            continue
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            continue
        if isinstance(value, str) and not is_ascii_only(value):
            warn_english_only()
            continue
        return value


if IS_ROOT_DIR:
    console.print("[bold red]КРИТИЧЕСКАЯ ОШИБКА:[/bold red]")
    console.print("[red]Обнаружена установка бота прямо в корневой папке (/root).[/red]")
    console.print("[red]Это крайне опасно и может привести к потере данных![/red]")
    console.print("[red]Рекомендуется перенести бота в отдельную папку, например /root/solobot[/red]")
    console.print("[red]Обновление заблокировано в целях безопасности.[/red]")
    sys.exit(1)


def is_service_exists(service_name):
    result = subprocess.run(["systemctl", "list-unit-files", service_name], capture_output=True, text=True)
    return service_name in result.stdout


def get_runtime_user() -> str:
    return os.environ.get("SUDO_USER") or subprocess.check_output(["whoami"], text=True).strip()


def has_project_code() -> bool:
    required_paths = ("requirements.txt", "main.py")
    return all(os.path.exists(os.path.join(PROJECT_DIR, path)) for path in required_paths)


def has_local_config() -> bool:
    return os.path.exists(os.path.join(PROJECT_DIR, "config.py"))


def bootstrap_project_files(branch: str = "main") -> bool:
    refresh_service_name()
    if has_project_code():
        return True

    console.print("[yellow]Полный проект рядом не найден. Подтягиваю файлы бота...[/yellow]")
    install_core_packages_if_needed()
    install_rsync_if_needed()

    subprocess.run(["rm", "-rf", TEMP_DIR], check=False)
    clone_result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, GITHUB_REPO, TEMP_DIR],
        check=False,
    )
    if clone_result.returncode != 0:
        console.print("[red]❌ Не удалось скачать проект из GitHub.[/red]")
        return False

    rsync_cmd = ["rsync", "-a", f"{TEMP_DIR}/", f"{PROJECT_DIR}/"]
    if has_local_config():
        rsync_cmd.insert(2, "--exclude=config.py")
    if os.path.exists(os.path.join(PROJECT_DIR, "handlers", "texts.py")):
        rsync_cmd.insert(2, "--exclude=handlers/texts.py")
    if os.path.exists(os.path.join(PROJECT_DIR, "handlers", "buttons.py")):
        rsync_cmd.insert(2, "--exclude=handlers/buttons.py")
    if os.path.exists(os.path.join(PROJECT_DIR, "core", "redis_cache.py")):
        rsync_cmd.insert(2, "--exclude=core/redis_cache.py")
    if os.path.exists(os.path.join(PROJECT_DIR, "img")):
        rsync_cmd.insert(2, "--exclude=img")
    if os.path.exists(os.path.join(PROJECT_DIR, "modules")):
        rsync_cmd.insert(2, "--exclude=modules")
    rsync_cmd.insert(2, "--exclude=.git")

    sync_result = subprocess.run(rsync_cmd, check=False)
    subprocess.run(["rm", "-rf", TEMP_DIR], check=False)
    if sync_result.returncode != 0:
        console.print("[red]❌ Не удалось распаковать файлы проекта.[/red]")
        return False

    refresh_service_name()
    console.print("[green]Файлы проекта подготовлены.[/green]")
    return True


def install_core_packages_if_needed():
    missing_packages = []

    if shutil.which("git") is None:
        missing_packages.append("git")
    if shutil.which("rsync") is None:
        missing_packages.append("rsync")

    python312_path = shutil.which("python3.12")
    if python312_path is None:
        missing_packages.extend(["python3.12", "python3.12-venv"])
    else:
        venv_check = subprocess.run(
            [python312_path, "-m", "venv", "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if venv_check.returncode != 0:
            missing_packages.append("python3.12-venv")

    if not missing_packages:
        return

    unique_packages = list(dict.fromkeys(missing_packages))
    console.print(f"[yellow]Устанавливаю системные пакеты: {', '.join(unique_packages)}[/yellow]")
    subprocess.run(["sudo", "apt", "update"], check=True)
    subprocess.run(["sudo", "apt", "install", "-y", *unique_packages], check=True)


def build_systemd_service() -> str:
    run_user = get_runtime_user()
    return (
        "[Unit]\n"
        "Description=SoloBot Telegram bot\n"
        "After=network.target\n\n"
        "[Service]\n"
        f"User={run_user}\n"
        f"WorkingDirectory={PROJECT_DIR}\n"
        f"ExecStart={VENV_PYTHON} {os.path.join(PROJECT_DIR, 'main.py')}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        'Environment="PYTHONUNBUFFERED=1"\n\n'
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def ensure_systemd_service() -> bool:
    refresh_service_name()
    console.print(f"[yellow]Проверяю systemd-службу {SERVICE_NAME}...[/yellow]")
    service_text = build_systemd_service()
    service_exists = os.path.exists(SYSTEMD_SERVICE_PATH)

    if service_exists:
        try:
            with open(SYSTEMD_SERVICE_PATH, encoding="utf-8") as service_file:
                if service_file.read() == service_text:
                    console.print(f"[green]Служба {SERVICE_NAME} уже настроена.[/green]")
                    return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["sudo", "tee", SYSTEMD_SERVICE_PATH],
            input=service_text,
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        console.print(f"[green]Служба {SERVICE_NAME} настроена.[/green]")
        return True
    except Exception as e:
        console.print(f"[red]❌ Не удалось настроить службу {SERVICE_NAME}: {e}[/red]")
        return False


def initialize_database() -> bool:
    if not os.path.exists(VENV_PYTHON):
        console.print("[yellow]Инициализация базы пропущена: виртуальное окружение ещё не создано.[/yellow]")
        return False
    console.print("[yellow]Инициализация базы данных...[/yellow]")
    try:
        subprocess.run(
            [
                VENV_PYTHON,
                "-c",
                "import asyncio; from database.setup.init_db import init_db; asyncio.run(init_db())",
            ],
            cwd=PROJECT_DIR,
            check=True,
        )
        console.print("[green]База данных успешно инициализирована.[/green]")
        return True
    except Exception as e:
        console.print(f"[red]❌ Не удалось инициализировать базу данных: {e}[/red]")
        return False


def enable_and_start_service(start_now: bool = True) -> None:
    refresh_service_name()
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", SERVICE_NAME], check=True)
    if start_now:
        subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME], check=True)
        console.print(f"[green]Служба {SERVICE_NAME} включена и запущена.[/green]")
    else:
        console.print(
            f"[yellow]Служба {SERVICE_NAME} включена, но не запущена. Проверьте config.py и доступность базы данных.[/yellow]"
        )


def is_runtime_ready() -> bool:
    refresh_service_name()
    if not has_project_code():
        return False
    return os.path.exists(VENV_PYTHON) and is_service_exists(SERVICE_NAME)


def install_bot():
    console.print(
        Panel(
            "[white]CLI подготовит окружение, установит зависимости, создаст systemd-службу "
            "и попробует инициализировать базу данных. Если проекта ещё нет рядом, CLI сначала скачает его автоматически.[/white]",
            border_style="green",
            title="[bold green]Автоматическая установка SoloBot[/bold green]",
            padding=(1, 2),
        )
    )

    if not safe_confirm("[bold green]Запустить автоматическую установку?[/bold green]", default=True):
        return

    try:
        branch = "main"
        if not has_project_code():
            use_beta = safe_confirm("[yellow]Скачать beta/dev ветку вместо стабильной?[/yellow]", default=False)
            branch = "dev" if use_beta else "main"
        if not bootstrap_project_files(branch=branch):
            return
        refresh_service_name()
        install_core_packages_if_needed()
        install_dependencies()
        db_ready = initialize_database()
        if not ensure_systemd_service():
            return
        fix_permissions()
        enable_and_start_service(start_now=db_ready)
        console.print("[green]✅ Установка SoloBot завершена.[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Ошибка во время установки: {e}[/red]")


def prompt_install_if_needed():
    if is_runtime_ready():
        return

    missing_parts = []
    if not has_project_code():
        missing_parts.append("файлы проекта")
    if has_project_code() and not os.path.exists(VENV_PYTHON):
        missing_parts.append("виртуальное окружение")
    refresh_service_name()
    if has_project_code() and not is_service_exists(SERVICE_NAME):
        missing_parts.append(f"служба {SERVICE_NAME}")

    console.print(f"[yellow]Обнаружена неполная установка: {', '.join(missing_parts)}.[/yellow]")
    if safe_confirm("[green]Выполнить автоматическую установку сейчас?[/green]", default=True):
        install_bot()


def print_logo():
    logo_lines = [
        "███████╗ ██████╗ ██╗      ██████╗ ██████╗  ██████╗ ████████╗",
        "██╔════╝██╔═══██╗██║     ██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝",
        "███████╗██║   ██║██║     ██║   ██║██████╔╝██║   ██║   ██║   ",
        "╚════██║██║   ██║██║     ██║   ██║██╔══██╗██║   ██║   ██║   ",
        "███████║╚██████╔╝███████╗╚██████╔╝██████╔╝╚██████╔╝   ██║   ",
        "╚══════╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝   ",
    ]

    with Live(refresh_per_second=10) as live:
        display = []
        for line in logo_lines:
            display.append(f"[bold cyan]{line}[/bold cyan]")
            panel = Panel(Group(*display), border_style="cyan", padding=(0, 2), expand=False)
            live.update(panel)
            sleep(0.07)

    local_version = get_local_version() or "unknown"
    last_update = get_last_update_date() or "unknown"
    console.print(f"[bold green]Директория бота:[/bold green] [yellow]{PROJECT_DIR}[/yellow]")
    console.print(f"[bold green]Установленная версия:[/bold green] [yellow]{local_version}[/yellow]")
    console.print(f"[bold green]Последнее обновление:[/bold green] [yellow]{last_update}[/yellow]\n")


def list_backups():
    if not os.path.isdir(BACK_DIR):
        return []
    pairs = []
    for name in os.listdir(BACK_DIR):
        path = os.path.join(BACK_DIR, name)
        if os.path.isdir(path):
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = 0
            pairs.append((mtime, path))
    pairs.sort(reverse=True)
    return [p for _, p in pairs]


def prune_old_backups():
    backups = list_backups()
    for path in backups[3:]:
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            subprocess.run(["sudo", "rm", "-rf", path])


def backup_project():
    from datetime import datetime

    os.makedirs(BACK_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACK_DIR, f"backup-{ts}")
    console.print("[yellow]Создаётся резервная копия проекта...[/yellow]")
    with console.status("[bold cyan]Копирование файлов...[/bold cyan]"):
        subprocess.run(["cp", "-r", PROJECT_DIR, dst])
    console.print(f"[green]Бэкап сохранён в: {dst}[/green]")
    prune_old_backups()


def restore_from_backup():
    from datetime import datetime

    backups = list_backups()[:3]
    if not backups:
        console.print(f"[red]❌ Бэкапы не найдены: {BACK_DIR}[/red]")
        return

    console.print("\n[bold green]Доступные бэкапы:[/bold green]")
    shown = []
    for idx, path in enumerate(backups, 1):
        try:
            mtime = os.path.getmtime(path)
            dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            dt = "unknown"
        console.print(f"[cyan]{idx}.[/cyan] {os.path.basename(path)}  [dim]{dt}[/dim]")
        shown.append((idx, path))

    try:
        choice = safe_prompt(
            "[bold blue]Выберите номер бэкапа[/bold blue]",
            choices=[str(i) for i, _ in shown],
        )
    except Exception:
        return

    sel_path = shown[int(choice) - 1][1]

    console.print("[red]Внимание: текущие файлы проекта будут перезаписаны выбранным бэкапом.[/red]")
    if not safe_confirm("[yellow]Продолжить восстановление из бэкапа?[/yellow]"):
        return

    if is_service_exists(SERVICE_NAME):
        console.print("[blue]Останавливаю службу перед восстановлением...[/blue]")
        subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME])

    install_rsync_if_needed()

    console.print("[yellow]Копирую файлы из бэкапа в проект...[/yellow]")
    rc = subprocess.run(
        ["rsync", "-a", "--delete", f"{sel_path}/", f"{PROJECT_DIR}/"],
        check=False,
    ).returncode
    if rc != 0:
        console.print("[red]❌ Ошибка rsync при восстановлении[/red]")
        return

    install_dependencies()
    fix_permissions()
    restart_service()
    console.print("[green]✅ Восстановление из бэкапа завершено[/green]")


def auto_update_cli():
    console.print("[yellow]Проверка обновлений CLI...[/yellow]")
    try:
        url = "https://raw.githubusercontent.com/Vladless/Solo_bot/dev/cli_launcher.py"
        response = http_get(url, timeout=10)
        if response.status_code != 200:
            console.print("[red]Не удалось получить обновление CLI[/red]")
            return

        latest_text = response.text
        current_path = os.path.realpath(__file__)
        with open(current_path, encoding="utf-8") as f:
            current_text = f.read()

        if current_text != latest_text:
            console.print("[green]Доступна новая версия CLI. Обновляю...[/green]")
            with open(current_path, "w", encoding="utf-8") as f:
                f.write(latest_text)
            os.chmod(current_path, 0o644)
            console.print("[green]CLI обновлён. Перезапуск...[/green]")
            os.execv(sys.executable, [sys.executable, current_path])
        else:
            console.print("[green]CLI уже актуален[/green]")
    except Exception as e:
        console.print(f"[red]❌ Ошибка при автообновлении CLI: {e}[/red]")


def fix_permissions():
    console.print("[yellow]Восстанавливаю владельца и права доступа к проекту...[/yellow]")

    try:
        user = os.environ.get("SUDO_USER") or subprocess.check_output(["whoami"], text=True).strip()
        console.log(f"[cyan]Используем пользователь: {user}[/cyan]")

        for root, dirs, files in os.walk(PROJECT_DIR):
            for dir in dirs:
                if dir == "__pycache__":
                    pycache_path = os.path.join(root, dir)
                    subprocess.run(["sudo", "rm", "-rf", pycache_path], check=True)
            for file in files:
                if file.endswith(".pyc"):
                    pyc_path = os.path.join(root, file)
                    subprocess.run(["sudo", "rm", "-f", pyc_path], check=True)

        console.log("[blue]Изменение владельца на весь проект...[/blue]")
        subprocess.run(["sudo", "chown", "-R", f"{user}:{user}", PROJECT_DIR], check=True)

        console.log("[blue]Изменение прав доступа (u=rwX,go=rX)...[/blue]")
        subprocess.run(["sudo", "chmod", "-R", "u=rwX,go=rX", PROJECT_DIR], check=True)

        launcher_path = os.path.join(PROJECT_DIR, "cli_launcher.py")
        if os.path.exists(launcher_path):
            console.log("[blue]Установка флага +x для cli_launcher.py...[/blue]")
            subprocess.run(["chmod", "+x", launcher_path], check=True)

        console.print(f"[green]Все права восстановлены для пользователя [bold]{user}[/bold][/green]")

    except Exception as e:
        console.print(f"[red]❌ Ошибка при установке прав: {e}[/red]")


def install_rsync_if_needed():
    install_core_packages_if_needed()


def clean_project_dir_safe(update_buttons=False, update_img=False, update_redis_cache=False):
    console.print("[yellow]Очистка проекта перед обновлением...[/yellow]")

    preserved_paths = set()

    preserved_paths.update([
        os.path.join(PROJECT_DIR, "config.py"),
        os.path.join(PROJECT_DIR, "handlers", "texts.py"),
        os.path.join(PROJECT_DIR, ".git"),
        os.path.join(PROJECT_DIR, "modules"),
    ])

    for root, dirs, files in os.walk(os.path.join(PROJECT_DIR, "modules")):
        for name in dirs + files:
            preserved_paths.add(os.path.join(root, name))

    if not update_buttons:
        preserved_paths.add(os.path.join(PROJECT_DIR, "handlers", "buttons.py"))

    if not update_img:
        preserved_paths.add(os.path.join(PROJECT_DIR, "img"))
        for root, dirs, files in os.walk(os.path.join(PROJECT_DIR, "img")):
            for name in dirs + files:
                preserved_paths.add(os.path.join(root, name))

    if not update_redis_cache:
        preserved_paths.add(os.path.join(PROJECT_DIR, "core", "redis_cache.py"))

    for root, dirs, files in os.walk(PROJECT_DIR, topdown=False):
        for file in files:
            path = os.path.join(root, file)
            if path in preserved_paths:
                continue
            try:
                os.remove(path)
            except PermissionError:
                subprocess.run(["sudo", "rm", "-f", path])
            except Exception as e:
                console.print(f"[red]Не удалось удалить файл: {path}: {e}[/red]")

        for dir in dirs:
            dir_path = os.path.join(root, dir)

            if os.path.abspath(dir_path) in [
                os.path.join(PROJECT_DIR, "handlers"),
                os.path.join(PROJECT_DIR, "img"),
                os.path.join(PROJECT_DIR, "modules"),
            ]:
                continue

            if os.path.abspath(dir_path).startswith(os.path.join(PROJECT_DIR, "modules") + os.sep):
                continue

            try:
                os.rmdir(dir_path)
            except Exception:
                subprocess.run(["sudo", "rm", "-rf", dir_path])


def install_git_if_needed():
    install_core_packages_if_needed()


def install_dependencies():
    console.print("[blue]Установка зависимостей...[/blue]")
    install_core_packages_if_needed()

    python312_path = shutil.which("python3.12")
    if not python312_path:
        console.print("[red]Не найден python3.12 в системе[/red]")
        console.print("[yellow]Установите Python 3.12: sudo apt install python3.12 python3.12-venv[/yellow]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(style="green"),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task_id = progress.add_task(description="Создание виртуального окружения...", total=None)
        try:
            if os.path.exists("venv"):
                shutil.rmtree("venv")
                console.print("[yellow]Удалён старый venv[/yellow]")

            subprocess.run([python312_path, "-m", "venv", "venv"], check=True)

            progress.update(task_id, description="Установка зависимостей...")
            subprocess.run(
                [os.path.join("venv", "bin", "pip"), "install", "-r", "requirements.txt"],
                check=True,
                cwd=PROJECT_DIR,
            )

            progress.update(task_id, description="Установка завершена")

        except subprocess.CalledProcessError as e:
            progress.update(task_id, description="❌ Ошибка при установке")
            console.print(f"[red]❌ Ошибка: {e}[/red]")


def restart_service():
    if ensure_systemd_service():
        console.print("[blue]🚀 Перезапуск службы...[/blue]")
        with console.status("[bold yellow]Перезапуск...[/bold yellow]"):
            subprocess.run(["sudo", "systemctl", "enable", SERVICE_NAME], check=False)
            subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME])


def get_local_version():
    try:
        result = subprocess.run(
            ["git", "-C", PROJECT_DIR, "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            check=False,
        )
        version = result.stdout.strip()
        if result.returncode == 0 and version:
            return version
    except Exception:
        pass

    path = os.path.join(PROJECT_DIR, "bot.py")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.search(r'version\s*=\s*["\'](.+?)["\']', line)
            if match:
                return match.group(1)
    return None


def get_last_update_date():
    try:
        result = subprocess.run(
            ["git", "-C", PROJECT_DIR, "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"],
            capture_output=True,
            text=True,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and value:
            return value
    except Exception:
        pass

    excluded_dirs = {".git", "venv", ".venv", "__pycache__", "build", "dist"}
    latest_mtime = 0.0
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for file_name in files:
            path = os.path.join(root, file_name)
            try:
                latest_mtime = max(latest_mtime, os.path.getmtime(path))
            except Exception:
                continue
    if latest_mtime <= 0:
        return None
    return datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")


def get_remote_version(branch="main"):
    try:
        url = f"https://raw.githubusercontent.com/Vladless/Solo_bot/{branch}/bot.py"
        response = http_get(url, timeout=10)
        if response.status_code == 200:
            for line in response.text.splitlines():
                match = re.search(r'version\s*=\s*["\'](.+?)["\']', line)
                if match:
                    return match.group(1)
    except Exception:
        return None
    return None


def update_from_beta():
    local_version = get_local_version()
    remote_version = get_remote_version(branch="dev")

    console.print(
        Panel(
            "[bold red]Обновление на DEV / BETA-ветку[/bold red]\n\n"
            "[white]"
            "• Dev-ветка может содержать изменения, которые ещё находятся в доработке.\n"
            "• Возможны ошибки и непредсказуемое поведение отдельных функций, особенно режима стран.\n\n"
            "• BETA-версии бота в первую очередь ориентированы на опытных пользователей, "
            "готовых протестировать новые возможности и осознанно работать с обновлённым функционалом.\n"
            "[/white]\n\n"
            "[yellow]Перед началом обновления CLI автоматически создаёт резервную копию проекта, "
            "что позволит при необходимости безопасно восстановиться из бэкапа.[/yellow]",
            border_style="red",
            title="[bold red]Нестабильная ветка разработки[/bold red]",
            padding=(1, 2),
        )
    )

    if local_version and remote_version:
        console.print(f"[cyan]Локальная версия: {local_version} | Последняя в dev: {remote_version}[/cyan]")
        if local_version == remote_version:
            if not safe_confirm("[yellow]Версия актуальна. Обновить всё равно?[/yellow]"):
                return

    if not safe_confirm(
        "[bold red]Продолжить обновление на dev-ветку с учётом возможных особенностей работы?[/bold red]"
    ):
        return

    console.print("[red]ВНИМАНИЕ! Папка бота будет перезаписана![/red]")
    if not safe_confirm("[red]Продолжить обновление?[/red]"):
        return

    update_buttons = safe_confirm("[yellow]Обновлять файл buttons.py?[/yellow]", default=False)
    update_img = safe_confirm("[yellow]Обновлять папку img?[/yellow]", default=False)
    update_redis_cache = safe_confirm("[yellow]Обновлять файл core/redis_cache.py?[/yellow]", default=False)

    backup_project()
    install_git_if_needed()
    install_rsync_if_needed()

    os.chdir(PROJECT_DIR)
    console.print("[cyan]Клонируем временный репозиторий...[/cyan]")
    subprocess.run(["rm", "-rf", TEMP_DIR])

    if os.system(f"git clone --depth=1000000 -b dev {GITHUB_REPO} {TEMP_DIR}") != 0:
        console.print("[red]❌ Ошибка при клонировании. Обновление отменено.[/red]")
        return

    subprocess.run(["sudo", "rm", "-rf", os.path.join(PROJECT_DIR, "venv")])
    clean_project_dir_safe(
        update_buttons=update_buttons,
        update_img=update_img,
        update_redis_cache=update_redis_cache,
    )

    exclude_options = ""
    if not update_img:
        exclude_options += "--exclude=img "
    if not update_buttons:
        exclude_options += "--exclude=handlers/buttons.py "
    if not update_redis_cache:
        exclude_options += "--exclude=core/redis_cache.py "
    exclude_options += "--exclude=modules "

    rsync_cmd = ["rsync", "-a"] + [x for x in exclude_options.split() if x] + [f"{TEMP_DIR}/", f"{PROJECT_DIR}/"]
    subprocess.run(rsync_cmd)

    modules_path = os.path.join(PROJECT_DIR, "modules")
    if not os.path.exists(modules_path):
        console.print("[yellow]Папка modules отсутствует — создаю вручную...[/yellow]")
        try:
            os.makedirs(modules_path, exist_ok=True)
            console.print("[green]Папка modules успешно создана.[/green]")
        except Exception as e:
            console.print(f"[red]❌ Не удалось создать папку modules: {e}[/red]")

    if os.path.exists(os.path.join(TEMP_DIR, ".git")):
        subprocess.run(["cp", "-r", os.path.join(TEMP_DIR, ".git"), PROJECT_DIR])

    subprocess.run(["rm", "-rf", TEMP_DIR])

    install_dependencies()
    fix_permissions()
    restart_service()
    console.print("[green]Обновление с ветки dev завершено.[/green]")


def _do_update_to_tag(tag_name: str, update_buttons: bool, update_img: bool, update_redis_cache: bool) -> None:
    """Общая логика обновления до указанного тега (релиз или произвольный тег)."""
    subprocess.run(["rm", "-rf", TEMP_DIR])
    subprocess.run(
        ["git", "clone", "--branch", tag_name, "--depth", "1", GITHUB_REPO, TEMP_DIR],
        check=True,
    )

    console.print("[red]Начинается перезапись файлов бота![/red]")
    subprocess.run(["sudo", "rm", "-rf", os.path.join(PROJECT_DIR, "venv")])
    clean_project_dir_safe(
        update_buttons=update_buttons,
        update_img=update_img,
        update_redis_cache=update_redis_cache,
    )

    exclude_options = ""
    if not update_img:
        exclude_options += "--exclude=img "
    if not update_buttons:
        exclude_options += "--exclude=handlers/buttons.py "
    if not update_redis_cache:
        exclude_options += "--exclude=core/redis_cache.py "
    exclude_options += "--exclude=modules "

    rsync_cmd = ["rsync", "-a"] + exclude_options.split() + [f"{TEMP_DIR}/", f"{PROJECT_DIR}/"]
    subprocess.run(rsync_cmd)

    modules_path = os.path.join(PROJECT_DIR, "modules")
    if not os.path.exists(modules_path):
        console.print("[yellow]Папка modules отсутствует — создаю вручную...[/yellow]")
        try:
            os.makedirs(modules_path, exist_ok=True)
            console.print("[green]Папка modules успешно создана.[/green]")
        except Exception as e:
            console.print(f"[red]❌ Не удалось создать папку modules: {e}[/red]")

    if os.path.exists(os.path.join(TEMP_DIR, ".git")):
        subprocess.run(["cp", "-r", os.path.join(TEMP_DIR, ".git"), PROJECT_DIR])

    subprocess.run(["rm", "-rf", TEMP_DIR])

    install_dependencies()
    fix_permissions()
    restart_service()
    console.print(f"[green]Обновление до {tag_name} завершено.[/green]")


def update_from_release():
    if not safe_confirm("[yellow]Подтвердите обновление Solobot до релиза или патча[/yellow]"):
        return

    console.print("[red]ВНИМАНИЕ! Папка бота будет полностью перезаписана![/red]")
    console.print("[red]  Исключения: папка img, файл handlers/buttons.py и файл core/redis_cache.py[/red]")
    if not safe_confirm("[red]Вы точно хотите продолжить?[/red]"):
        return

    update_buttons = safe_confirm("[yellow]Обновлять файл buttons.py?[/yellow]", default=False)
    update_img = safe_confirm("[yellow]Обновлять папку img?[/yellow]", default=False)
    update_redis_cache = safe_confirm("[yellow]Обновлять файл core/redis_cache.py?[/yellow]", default=False)

    backup_project()
    install_git_if_needed()
    install_rsync_if_needed()

    try:
        rel_resp = http_get(
            "https://api.github.com/repos/Vladless/Solo_bot/releases",
            timeout=10,
        )
        releases = rel_resp.json() if rel_resp.status_code == 200 else []
        release_tag_names = {r["tag_name"] for r in releases}

        tags_resp = http_get(
            "https://api.github.com/repos/Vladless/Solo_bot/tags",
            params={"per_page": 50},
            timeout=10,
        )
        if tags_resp.status_code != 200:
            raise ValueError("Не удалось получить список тегов")
        tags_data = tags_resp.json()
        all_tag_names = [t["name"] for t in tags_data]

        tag_names = [name for name in all_tag_names if _parse_tag_version(name)[0] >= 4]
        tag_names.sort(key=_parse_tag_version)

        if not tag_names:
            raise ValueError("Нет доступных тегов (ожидаются версии начиная с 4)")

        console.print("\n[bold green]Релизы и патчи:[/bold green]")
        for idx, name in enumerate(tag_names, 1):
            label = " [dim](релиз)[/dim]" if name in release_tag_names else " [dim](патч)[/dim]"
            console.print(f"[cyan]{idx}.[/cyan] {name}{label}")

        choices = [str(i) for i in range(1, len(tag_names) + 1)]
        selected = safe_prompt(
            "[bold blue]Выберите номер версии[/bold blue]",
            choices=choices,
        )
        tag_name = tag_names[int(selected) - 1]

        if not safe_confirm(f"[yellow]Установить {tag_name}?[/yellow]"):
            return

        console.print(f"[cyan]Клонируем {tag_name} во временную папку...[/cyan]")
        _do_update_to_tag(tag_name, update_buttons, update_img, update_redis_cache)

    except Exception as e:
        console.print(f"[red]❌ Ошибка при обновлении: {e}[/red]")


WEB_IMAGE = "ghcr.io/vladless/solo-brick:latest"
WEB_CONTAINER_NAME = "solo-brick"
WEB_DIR = os.path.join(os.path.expanduser("~"), "solo-brick")
WEB_REMOTE_ARCHIVE = "https://github.com/Vladless/Solo_bot/archive/refs/heads/dev.tar.gz"
WEB_REMOTE_SUBDIR = "web-app"


def _find_local_web_source() -> str | None:
    candidates = [
        os.path.join(PROJECT_DIR, "web-app"),
        os.path.join(os.path.dirname(PROJECT_DIR), "web-app"),
        os.path.join(os.path.expanduser("~"), "Solo_bot", "web-app"),
    ]
    for path in candidates:
        if (
            os.path.isdir(path)
            and os.path.isfile(os.path.join(path, "package.json"))
            and os.path.isfile(os.path.join(path, "Dockerfile"))
        ):
            return path
    return None


def _copy_local_web_source(src: str, dst: str) -> bool:
    subprocess.run(["rm", "-rf", dst], check=False)
    if shutil.which("rsync"):
        result = subprocess.run(
            [
                "rsync", "-a",
                "--exclude=node_modules",
                "--exclude=.next",
                "--exclude=.git",
                "--exclude=.env",
                "--exclude=.env.local",
                "--exclude=.env.production",
                "--exclude=logs",
                "--exclude=.deploy",
                "--exclude=.data",
                "--exclude=.claude",
                f"{src}/",
                f"{dst}/",
            ],
            check=False,
        )
        if result.returncode != 0:
            return False
    else:
        try:
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns(
                    "node_modules", ".next", ".git", ".env", ".env.local",
                    ".env.production", "logs", ".deploy", ".data", ".claude",
                ),
            )
        except Exception:
            return False
    return os.path.isfile(os.path.join(dst, "package.json"))


def _download_web_from_github(dst: str) -> bool:
    import urllib.request
    import tarfile
    import tempfile

    subprocess.run(["rm", "-rf", dst], check=False)
    os.makedirs(dst, exist_ok=True)

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(WEB_REMOTE_ARCHIVE, tmp_path)

        with tarfile.open(tmp_path, "r:gz") as tar:
            prefix_marker = f"/{WEB_REMOTE_SUBDIR}/"
            extracted = 0
            for member in tar.getmembers():
                idx = member.name.find(prefix_marker)
                if idx == -1:
                    continue
                relative = member.name[idx + len(prefix_marker):]
                if not relative:
                    continue
                member.name = relative
                tar.extract(member, dst)
                extracted += 1
            if extracted == 0:
                return False
    except Exception as e:
        console.print(f"[red]❌ Ошибка загрузки архива: {e}[/red]")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return os.path.isfile(os.path.join(dst, "package.json"))


def _prepare_web_sources(dst: str) -> bool:
    local = _find_local_web_source()
    if local:
        console.print(f"[cyan]Найден локальный web-app: {local}[/cyan]")
        if _copy_local_web_source(local, dst):
            console.print("[green]✓ Локальные исходники скопированы[/green]")
            return True
        console.print("[yellow]Не удалось скопировать локальные исходники. Пробую загрузку из GitHub.[/yellow]")

    console.print("[cyan]Загрузка web-app из публичного репозитория Vladless/Solo_bot (dev)...[/cyan]")
    if _download_web_from_github(dst):
        console.print("[green]✓ Исходники загружены из публичного репозитория[/green]")
        return True

    console.print("[red]❌ Не удалось получить исходники web-app[/red]")
    return False


def _pull_web_image() -> bool:
    console.print(f"[cyan]Загрузка готового образа: {WEB_IMAGE}[/cyan]")
    result = subprocess.run(
        ["docker", "pull", WEB_IMAGE],
        check=False,
    )
    return result.returncode == 0


def _build_web_image(src_dir: str) -> bool:
    if not os.path.isfile(os.path.join(src_dir, "package.json")):
        if not _prepare_web_sources(src_dir):
            return False
    if not os.path.isfile(os.path.join(src_dir, "Dockerfile")):
        console.print("[red]❌ В исходниках нет Dockerfile[/red]")
        return False
    console.print("[cyan]Сборка Docker-образа (несколько минут)...[/cyan]")
    result = subprocess.run(
        ["docker", "build", "-t", WEB_IMAGE, "."],
        cwd=src_dir, check=False,
    )
    if result.returncode != 0:
        console.print("[red]❌ Ошибка сборки. Проверьте логи выше.[/red]")
        return False
    return True


def _ensure_web_image(src_dir: str, force_pull: bool = False) -> bool:
    if _pull_web_image():
        console.print(f"[green]✓ Образ {WEB_IMAGE} получен из GHCR[/green]")
        return True

    console.print("[yellow]Не удалось скачать образ из GHCR. Пробую локальную сборку.[/yellow]")
    return _build_web_image(src_dir)


def _check_feature(name: str) -> bool:
    try:
        from core.rpc import check_feature
        return check_feature(name)
    except Exception:
        return False


def _verify_license_for_web(code: str, password: str) -> tuple[bool, str]:
    try:
        from core.rpc import verify_web_license
        return verify_web_license(code, password)
    except Exception:
        return False, ""


def _ensure_docker():
    """Проверяет/устанавливает Docker."""
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except subprocess.CalledProcessError:
            console.print("[yellow]Docker установлен, но не запущен.[/yellow]")
            subprocess.run(["sudo", "systemctl", "start", "docker"], check=False)
            return True
    console.print("[cyan]Установка Docker...[/cyan]")
    try:
        subprocess.run("curl -fsSL https://get.docker.com | sh", shell=True, check=True)
        subprocess.run(["sudo", "systemctl", "enable", "docker"], check=False)
        subprocess.run(["sudo", "systemctl", "start", "docker"], check=False)
        return True
    except subprocess.CalledProcessError:
        console.print("[red]❌ Не удалось установить Docker.[/red]")
        return False


def _ensure_nginx():
    """Проверяет/устанавливает nginx."""
    if shutil.which("nginx"):
        return True
    console.print("[cyan]Установка nginx...[/cyan]")
    try:
        subprocess.run(["sudo", "apt-get", "update", "-qq"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "nginx"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["sudo", "systemctl", "enable", "nginx"], check=False)
        subprocess.run(["sudo", "systemctl", "start", "nginx"], check=False)
        return True
    except subprocess.CalledProcessError:
        console.print("[yellow]Не удалось установить nginx автоматически.[/yellow]")
        return False


def _setup_nginx(domain, web_port=3000):
    """Настраивает nginx reverse proxy."""
    conf = f"""server {{
    listen 80;
    server_name {domain};
    client_max_body_size 100m;

    location /_next/static/ {{
        proxy_pass http://127.0.0.1:{web_port};
        proxy_cache_valid 200 365d;
        add_header Cache-Control "public, immutable, max-age=31536000";
    }}

    location = /sw.js {{
        proxy_pass http://127.0.0.1:{web_port};
        add_header Cache-Control "no-cache";
    }}

    location / {{
        proxy_pass http://127.0.0.1:{web_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }}
}}"""
    conf_path = f"/etc/nginx/sites-available/solo-{domain}"
    enabled_path = f"/etc/nginx/sites-enabled/solo-{domain}"
    try:
        with open("/tmp/_solo_nginx.conf", "w") as f:
            f.write(conf)
        subprocess.run(["sudo", "cp", "/tmp/_solo_nginx.conf", conf_path], check=True)
        subprocess.run(["sudo", "ln", "-sf", conf_path, enabled_path], check=True)
        subprocess.run(["sudo", "rm", "-f", "/etc/nginx/sites-enabled/default"], check=False)
        subprocess.run(["sudo", "nginx", "-t"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
        return True
    except subprocess.CalledProcessError:
        console.print("[yellow]Не удалось настроить nginx.[/yellow]")
        return False


def _setup_ssl(domain):
    """Получает SSL сертификат через certbot."""
    if not shutil.which("certbot"):
        try:
            subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "certbot", "python3-certbot-nginx"],
                           check=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            console.print("[yellow]Не удалось установить certbot.[/yellow]")
            return False
    try:
        subprocess.run([
            "sudo", "certbot", "--nginx", "-d", domain,
            "--non-interactive", "--agree-tos", "--register-unsafely-without-email", "--redirect",
        ], check=True)
        return True
    except subprocess.CalledProcessError:
        console.print(f"[yellow]Не удалось получить SSL. Убедитесь что {domain} указывает на этот сервер.[/yellow]")
        console.print(f"[dim]Повторите вручную: sudo certbot --nginx -d {domain}[/dim]")
        return False


def install_website():
    """Устанавливает веб-приложение (сайт) через Docker."""
    if not _check_feature("web"):
        console.print("[yellow]Эта функция недоступна в текущей версии. Обновите бота.[/yellow]")
        return

    console.print(
        Panel(
            "[white]CLI установит Docker, скачает готовый образ сайта, настроит nginx и SSL.\n"
            "Бэкенд (бот) может быть на этом же сервере или на другом.[/white]",
            border_style="green",
            title="[bold green]Установка веб-приложения[/bold green]",
            padding=(1, 2),
        )
    )

    console.print(
        Panel(
            "[bold cyan]Вариант A:[/bold cyan] Бот и сайт на одном сервере\n"
            "  → Адрес API: http://localhost:8000 (по умолчанию)\n\n"
            "[bold cyan]Вариант B:[/bold cyan] Сайт на отдельном сервере\n"
            "  → Адрес API: http://IP-бота:8000 (укажите IP сервера с ботом)\n"
            "  → На сервере бота должен быть открыт порт 8000",
            border_style="dim",
            title="[dim]Варианты размещения[/dim]",
            padding=(1, 2),
        )
    )

    if not safe_confirm("[bold green]Начать установку сайта?[/bold green]", default=True):
        return

    console.print("\n[bold][0/5] Авторизация[/bold]")
    console.print("[dim]Введите логин и пароль от вашего кабинета на сайте Solo.[/dim]")
    console.print("[dim]Данные используются только для проверки лицензии и нигде не сохраняются.[/dim]\n")

    lc_code = safe_prompt("[cyan]Логин (Client Code)[/cyan]")
    if not lc_code or not lc_code.strip():
        console.print("[red]Логин обязателен.[/red]")
        return

    try:
        import getpass
        lc_pass = getpass.getpass("  Пароль: ")
    except Exception:
        lc_pass = safe_prompt("[cyan]Пароль[/cyan]")

    if not lc_pass or not lc_pass.strip():
        console.print("[red]Пароль обязателен.[/red]")
        return

    console.print("[dim]Проверка лицензии...[/dim]")
    lc_ok, lc_msg = _verify_license_for_web(lc_code.strip(), lc_pass.strip())
    lc_code = None
    lc_pass = None

    if not lc_ok:
        console.print(f"[red]❌ {lc_msg or 'Авторизация не пройдена'}[/red]")
        return
    console.print("[green]✓ Авторизация пройдена[/green]")

    console.print("\n[bold][1/5] Docker[/bold]")
    if not _ensure_docker():
        return

    console.print("\n[bold][2/5] Настройки[/bold]\n")

    console.print("[dim]Домен, по которому будет открываться сайт.\nDNS (A-запись) должна уже указывать на IP этого сервера.[/dim]")
    domain = safe_prompt("[cyan]Домен сайта[/cyan] (например vpn.example.com)")
    if not domain or not domain.strip():
        console.print("[red]Домен обязателен.[/red]")
        return
    domain = domain.strip()

    try:
        from config import API_PORT as _BOT_API_PORT
        _bot_api_port = int(_BOT_API_PORT)
    except Exception:
        _bot_api_port = 3004
    _api_default = f"http://localhost:{_bot_api_port}"
    console.print(f"\n[dim]Адрес API вашего бота (FastAPI).\nЕсли бот на этом же сервере — оставьте по умолчанию.\nЕсли на другом — укажите полный адрес, например http://123.45.67.89:{_bot_api_port}[/dim]")
    api_url = safe_prompt("[cyan]Адрес backend API[/cyan]", default=_api_default)

    console.print("\n[dim]Внутренний порт, на котором запустится сайт.\nNginx проксирует на него запросы. Менять нужно только если порт занят.[/dim]")
    web_port = safe_prompt("[cyan]Порт сайта[/cyan]", default="3000")

    console.print("\n[dim]Для push-уведомлений на сайте (колокольчик).\nГенерируется командой: npx web-push generate-vapid-keys\nЕсли не нужны — пропустите.[/dim]")
    vapid_key = safe_prompt("[cyan]VAPID Public Key[/cyan] (Enter — пропустить)", default="")

    console.print("\n[dim]Cloudflare Turnstile защищает формы логина от ботов.\nПолучите ключ на dash.cloudflare.com → Turnstile.\nЕсли не нужно — пропустите, формы будут работать без CAPTCHA.[/dim]")
    turnstile_key = safe_prompt("[cyan]Turnstile Site Key[/cyan] (Enter — пропустить)", default="")

    console.print("\n[dim]Username Telegram-бота (без @) для кнопки «Войти через Telegram» на сайте.\nЕсли не нужно — пропустите.[/dim]")
    tg_bot_username = safe_prompt("[cyan]Telegram Bot Username[/cyan] (Enter — пропустить)", default="")

    console.print("\n[dim]Для отправки email-кодов (логин, подтверждение, сброс пароля).\nЕсли не нужно — пропустите, регистрация по email+паролю будет работать без этого.[/dim]")
    smtp_host = safe_prompt("[cyan]SMTP Host[/cyan] (Enter — пропустить)", default="")
    smtp_user = ""
    smtp_password = ""
    smtp_from = ""
    if smtp_host:
        smtp_user = safe_prompt("[cyan]SMTP User[/cyan]", default="")
        try:
            import getpass
            smtp_password = getpass.getpass("  SMTP Password: ")
        except Exception:
            smtp_password = safe_prompt("[cyan]SMTP Password[/cyan]", default="")
        smtp_from = safe_prompt("[cyan]Email From[/cyan]", default=smtp_user)

    setup_ssl = safe_confirm("[cyan]Установить SSL (Let's Encrypt)?[/cyan]", default=True)

    site_url = f"https://{domain}" if setup_ssl else f"http://{domain}"

    console.print(f"\n  Домен:   [green]{domain}[/green]")
    console.print(f"  Backend: [green]{api_url}[/green]")
    console.print(f"  SSL:     [green]{'Да' if setup_ssl else 'Нет'}[/green]")

    if not safe_confirm("\n[yellow]Всё верно?[/yellow]", default=True):
        return

    console.print("\n[bold][3/5] Запуск сайта[/bold]")
    os.makedirs(WEB_DIR, exist_ok=True)

    from urllib.parse import urlparse
    parsed_api = urlparse(api_url)
    api_port_from_url = ""
    if parsed_api.port is not None:
        api_port_from_url = str(parsed_api.port)
    elif parsed_api.scheme == "https":
        api_port_from_url = "443"
    elif parsed_api.scheme == "http":
        api_port_from_url = "80"

    env_path = os.path.join(WEB_DIR, ".env")
    with open(env_path, "w") as f:
        f.write(f"API_URL={api_url}\n")
        f.write(f"API_BASE_URL={api_url}\n")
        f.write(f"NEXT_PUBLIC_API_URL={api_url}\n")
        f.write(f"NEXT_PUBLIC_API_BASE_URL={api_url}\n")
        f.write(f"NEXT_PUBLIC_API_PORT={api_port_from_url}\n")
        f.write(f"NEXT_PUBLIC_SITE_URL={site_url}\n")
        f.write(f"NEXT_PUBLIC_VAPID_PUBLIC_KEY={vapid_key}\n")
        f.write(f"NEXT_PUBLIC_TURNSTILE_SITE_KEY={turnstile_key}\n")
        f.write(f"NEXT_PUBLIC_LOG_LEVEL=info\n")
        f.write(f"WEB_PORT={web_port}\n")
        if tg_bot_username:
            f.write(f"NEXT_PUBLIC_TELEGRAM_BOT_USERNAME={tg_bot_username}\n")
        if smtp_host:
            f.write(f"EMAIL_SMTP_HOST={smtp_host}\n")
            f.write(f"EMAIL_SMTP_PORT=465\n")
            f.write(f"EMAIL_SMTP_USER={smtp_user}\n")
            f.write(f"EMAIL_SMTP_PASSWORD={smtp_password}\n")
            f.write(f"EMAIL_FROM={smtp_from}\n")

    src_dir = os.path.join(WEB_DIR, "src")
    if not _ensure_web_image(src_dir):
        return

    compose_path = os.path.join(WEB_DIR, "docker-compose.yml")
    with open(compose_path, "w") as f:
        f.write(f"""name: {WEB_CONTAINER_NAME}

services:
  web:
    image: {WEB_IMAGE}
    container_name: {WEB_CONTAINER_NAME}
    ports:
      - "127.0.0.1:{web_port}:3000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    volumes:
      - ./logs:/app/logs
""")

    console.print("[cyan]Запуск контейнера...[/cyan]")
    subprocess.run(["docker", "compose", "up", "-d"], cwd=WEB_DIR, check=True)
    console.print(f"[green]✅ Контейнер запущен на порту {web_port}[/green]")

    console.print("\n[bold][4/5] Nginx[/bold]")
    if _ensure_nginx():
        _setup_nginx(domain, int(web_port))
        console.print(f"[green]✅ nginx настроен для {domain}[/green]")

    console.print("\n[bold][5/5] SSL[/bold]")
    if setup_ssl:
        if _setup_ssl(domain):
            console.print("[green]✅ SSL сертификат установлен[/green]")
    else:
        console.print("[dim]SSL пропущен[/dim]")

    smtp_hint = ""
    if not smtp_host:
        smtp_hint = "\n\n[yellow]⚠ SMTP не настроен — вход по email-коду и сброс пароля не будут работать.\n  Настройте позже через: меню → Управление сайтом → Изменить настройки[/yellow]"

    console.print(
        Panel(
            f"[bold green]Сайт доступен: {site_url}[/bold green]{smtp_hint}\n\n"
            f"[white]Управление:[/white]\n"
            f"  cd {WEB_DIR}\n"
            f"  docker compose logs -f       [dim]— логи[/dim]\n"
            f"  docker compose restart       [dim]— перезапуск[/dim]\n"
            f"  docker compose down          [dim]— остановка[/dim]\n"
            f"  nano .env                    [dim]— настройки[/dim]",
            border_style="green",
            title="[bold green]✅ Установка завершена[/bold green]",
            padding=(1, 2),
        )
    )


def manage_website():
    """Меню управления сайтом."""
    if not _check_feature("web"):
        console.print("[yellow]Эта функция недоступна в текущей версии. Обновите бота.[/yellow]")
        return
    if not os.path.exists(os.path.join(WEB_DIR, "docker-compose.yml")):
        console.print("[yellow]Сайт не установлен.[/yellow]")
        if safe_confirm("[green]Установить сейчас?[/green]", default=True):
            install_website()
        return

    table = Table(title="Управление сайтом", title_style="bold cyan", header_style="bold blue")
    table.add_column("№", justify="center", style="cyan", no_wrap=True)
    table.add_column("Действие", style="white")
    table.add_row("1", "Показать статус")
    table.add_row("2", "Показать логи")
    table.add_row("3", "Перезапустить")
    table.add_row("4", "Остановить")
    table.add_row("5", "Обновить (пересборка + restart)")
    table.add_row("6", "Изменить настройки (.env)")
    table.add_row("7", "Переустановить")
    table.add_row("8", "Назад")
    console.print(table)

    choice = safe_prompt("[bold blue]👉 Выберите действие[/bold blue]",
                         choices=[str(i) for i in range(1, 9)], show_choices=False)

    if choice == "1":
        subprocess.run(["docker", "compose", "ps"], cwd=WEB_DIR)
    elif choice == "2":
        subprocess.run(["docker", "compose", "logs", "--tail", "80", "-f"], cwd=WEB_DIR)
    elif choice == "3":
        subprocess.run(["docker", "compose", "restart"], cwd=WEB_DIR)
        console.print("[green]✅ Перезапущено[/green]")
    elif choice == "4":
        subprocess.run(["docker", "compose", "down"], cwd=WEB_DIR)
        console.print("[yellow]Сайт остановлен[/yellow]")
    elif choice == "5":
        src_dir = os.path.join(WEB_DIR, "src")
        console.print("[cyan]Обновление образа...[/cyan]")
        if not _ensure_web_image(src_dir, force_pull=True):
            return
        subprocess.run(["docker", "compose", "up", "-d", "--force-recreate"], cwd=WEB_DIR)
        console.print("[green]✅ Обновлено[/green]")
    elif choice == "6":
        env_path = os.path.join(WEB_DIR, ".env")
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, env_path])
        if safe_confirm("[cyan]Перезапустить сайт с новыми настройками?[/cyan]", default=True):
            subprocess.run(["docker", "compose", "restart"], cwd=WEB_DIR)
    elif choice == "7":
        install_website()


def show_update_menu():
    if IS_ROOT_DIR:
        console.print("[red]Обновление невозможно: бот находится в /root[/red]")
        console.print("[yellow]Перенесите бота в отдельную папку и повторите попытку[/yellow]")
        return

    table = Table(title="Выберите способ обновления", title_style="bold green")
    table.add_column("№", justify="center", style="cyan", no_wrap=True)
    table.add_column("Источник", style="white")
    table.add_row("1", "Обновить до BETA")
    table.add_row("2", "Обновить до релиза (релизы и патчи)")
    table.add_row("3", "Назад в меню")

    console.print(table)
    choice = safe_prompt("[bold blue]Введите номер[/bold blue]", choices=["1", "2", "3"])

    if choice == "1":
        update_from_beta()
    elif choice == "2":
        update_from_release()


def show_menu():
    table = Table(title="Solobot CLI v0.5.3", title_style="bold magenta", header_style="bold blue")
    table.add_column("№", justify="center", style="cyan", no_wrap=True)
    table.add_column("Операция", style="white")
    table.add_row("1", "Запустить бота (systemd)")
    table.add_row("2", "Запустить напрямую: venv/bin/python main.py")
    table.add_row("3", "Перезапустить бота (systemd)")
    table.add_row("4", "Остановить бота (systemd)")
    table.add_row("5", "Показать логи (80 строк)")
    table.add_row("6", "Показать статус")
    table.add_row("7", "Обновить Solobot")
    table.add_row("8", "Восстановить из бэкапа")
    table.add_row("9", "Установить / переустановить бота")
    table.add_row("10", "🌐 Веб-сайт (установка / управление)")
    table.add_row("11", "Выход")
    console.print(table)


def main():
    os.chdir(PROJECT_DIR)
    auto_update_cli()
    print_logo()
    prompt_install_if_needed()
    try:
        while True:
            refresh_service_name()
            show_menu()
            choice = safe_prompt(
                "[bold blue]👉 Введите номер действия[/bold blue]",
                choices=[str(i) for i in range(1, 12)],
                show_choices=False,
            )
            if choice == "1":
                if is_service_exists(SERVICE_NAME):
                    subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME])
                else:
                    console.print(f"[yellow]Служба {SERVICE_NAME} не найдена.[/yellow]")
                    if safe_confirm("[green]Установить бота и создать службу сейчас?[/green]", default=True):
                        install_bot()
            elif choice == "2":
                if not os.path.exists(VENV_PYTHON):
                    console.print("[yellow]Виртуальное окружение ещё не создано.[/yellow]")
                    if safe_confirm("[green]Подготовить окружение через автоматическую установку?[/green]", default=True):
                        install_bot()
                    continue
                if safe_confirm("[green]Вы действительно хотите запустить main.py вручную?[/green]"):
                    subprocess.run(["venv/bin/python", "main.py"])
            elif choice == "3":
                if is_service_exists(SERVICE_NAME):
                    if safe_confirm("[yellow]Вы действительно хотите перезапустить бота?[/yellow]"):
                        subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "4":
                if is_service_exists(SERVICE_NAME):
                    if safe_confirm("[red]Вы уверены, что хотите остановить бота?[/red]"):
                        subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "5":
                if is_service_exists(SERVICE_NAME):
                    subprocess.run([
                        "sudo",
                        "journalctl",
                        "-u",
                        SERVICE_NAME,
                        "-n",
                        "80",
                        "--no-pager",
                    ])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "6":
                if is_service_exists(SERVICE_NAME):
                    subprocess.run(["sudo", "systemctl", "status", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "7":
                show_update_menu()
            elif choice == "8":
                restore_from_backup()
            elif choice == "9":
                install_bot()
            elif choice == "10":
                manage_website()
            elif choice == "11":
                console.print("[bold cyan]Выход из CLI. Удачного дня![/bold cyan]")
                break
    except KeyboardInterrupt:
        console.print("\n[bold red]⏹ Прерывание. Выход из CLI.[/bold red]")


if __name__ == "__main__":
    main()
