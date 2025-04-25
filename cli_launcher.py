import os
import re
import subprocess
import sys

import requests

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from config import BOT_SERVICE


try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

if not os.environ.get("LC_ALL", "").endswith("UTF-8"):
    os.environ["LC_ALL"] = "en_US.UTF-8"
    os.environ["LANG"] = "en_US.UTF-8"

BACK_DIR = os.path.expanduser("~/.solobot_backup")
TEMP_DIR = os.path.expanduser("~/.solobot_tmp")
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
GITHUB_REPO = "https://github.com/Vladless/Solo_bot"
SERVICE_NAME = BOT_SERVICE

console = Console()


def is_service_exists(service_name):
    result = subprocess.run(["systemctl", "list-unit-files", service_name], capture_output=True, text=True)
    return service_name in result.stdout


def print_logo():
    logo = Text(
        """
███████╗ ██████╗ ██╗      ██████╗ ██████╗  ██████╗ ████████╗
██╔════╝██╔═══██╗██║     ██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝
███████╗██║   ██║██║     ██║   ██║██████╔╝██║   ██║   ██║   
╚════██║██║   ██║██║     ██║   ██║██╔══██╗██║   ██║   ██║   
███████║╚██████╔╝███████╗╚██████╔╝██████╔╝╚██████╔╝   ██║   
╚══════╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝   
""",
        style="bold cyan",
    )
    console.print(logo)


def backup_project():
    console.print("[yellow]📦 Создаётся резервная копия проекта...[/yellow]")
    with console.status("[bold cyan]Копирование файлов...[/bold cyan]"):
        subprocess.run(["rm", "-rf", BACK_DIR])
        subprocess.run(["cp", "-r", PROJECT_DIR, BACK_DIR])
    console.print(f"[green]✅ Бэкап сохранён в: {BACK_DIR}[/green]")


def install_rsync_if_needed():
    if subprocess.run(["which", "rsync"], capture_output=True).returncode != 0:
        console.print("[blue]📦 Установка rsync...[/blue]")
        os.system("sudo apt update && sudo apt install -y rsync")


def clean_project_dir_safe():
    console.print("[yellow]🧹 Очистка проекта перед обновлением (кроме config и кнопок)...[/yellow]")
    preserved_paths = {
        os.path.join(PROJECT_DIR, "config.py"),
        os.path.join(PROJECT_DIR, "handlers", "buttons.py"),
        os.path.join(PROJECT_DIR, "handlers", "texts.py"),
    }

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
            if os.path.abspath(dir_path) == os.path.join(PROJECT_DIR, "handlers"):
                continue
            try:
                os.rmdir(dir_path)
            except Exception:
                subprocess.run(["sudo", "rm", "-rf", dir_path])


def install_git_if_needed():
    if subprocess.run(["which", "git"], capture_output=True).returncode != 0:
        console.print("[blue]Установка Git...[/blue]")
        os.system("sudo apt update && sudo apt install -y git")


def install_dependencies():
    console.print("[blue]🔧 Установка зависимостей...[/blue]")
    with console.status("[bold green]Устанавливаются зависимости...[/bold green]"):
        try:
            if not os.path.exists("venv"):
                console.print("[yellow]⚠️ Виртуальное окружение не найдено. Создаю...[/yellow]")
                subprocess.run("python3 -m venv venv", shell=True, check=True)

            subprocess.run(
                "bash -c 'source venv/bin/activate && pip install -r requirements.txt'", shell=True, check=True
            )
        except subprocess.CalledProcessError:
            console.print("[red]❌ Ошибка при установке зависимостей.[/red]")


def restart_service():
    if is_service_exists(SERVICE_NAME):
        console.print("[blue]🚀 Перезапуск службы...[/blue]")
        with console.status("[bold yellow]Перезапуск...[/bold yellow]"):
            subprocess.run(f"sudo systemctl restart {SERVICE_NAME}", shell=True)
    else:
        console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")


def get_local_version():
    path = os.path.join(PROJECT_DIR, "bot.py")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.search(r'version\s*=\s*["\'](.+?)["\']', line)
            if match:
                return match.group(1)
    return None


def get_remote_version(branch="main"):
    try:
        url = f"https://raw.githubusercontent.com/Vladless/Solo_bot/{branch}/bot.py"
        response = requests.get(url, timeout=10)
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

    if local_version and remote_version:
        console.print(f"[cyan]🔢 Локальная версия: {local_version} | Последняя в dev: {remote_version}[/cyan]")
        if local_version == remote_version:
            if not Confirm.ask("[yellow]❗ Версия актуальна. Обновить всё равно?[/yellow]"):
                return
    else:
        console.print("[red]⚠️ Не удалось определить версии.[/red]")

    if not Confirm.ask("[yellow]🔁 Подтвердите обновление Solobot с ветки DEV[/yellow]"):
        return

    backup_project()
    install_git_if_needed()
    install_rsync_if_needed()

    os.chdir(PROJECT_DIR)
    console.print("[cyan]📅 Клонируем временный репозиторий...[/cyan]")
    subprocess.run(["rm", "-rf", TEMP_DIR])
    if os.system(f"git clone -b dev {GITHUB_REPO} {TEMP_DIR}") != 0:
        console.print("[red]❌ Ошибка при клонировании. Обновление отменено.[/red]")
        return

    subprocess.run(["sudo", "rm", "-rf", os.path.join(PROJECT_DIR, "venv")])
    clean_project_dir_safe()
    subprocess.run(f"rsync -a --exclude=img --exclude=handlers/buttons.py {TEMP_DIR}/ {PROJECT_DIR}/", shell=True)
    subprocess.run(["rm", "-rf", TEMP_DIR])

    install_dependencies()
    restart_service()
    console.print("[green]✅ Обновление с ветки dev завершено.[/green]")


def update_from_release():
    if not Confirm.ask("[yellow]🔁 Подтвердите обновление Solobot до одного из последних релизов[/yellow]"):
        return

    backup_project()
    install_git_if_needed()
    install_rsync_if_needed()

    try:
        response = requests.get("https://api.github.com/repos/Vladless/Solo_bot/releases", timeout=10)
        releases = response.json()[:3]
        tag_choices = [r["tag_name"] for r in releases]

        if not tag_choices:
            raise ValueError("Не удалось получить список релизов")

        console.print("\n[bold green]Доступные релизы:[/bold green]")
        for idx, tag in enumerate(tag_choices, 1):
            console.print(f"[cyan]{idx}.[/cyan] {tag}")

        selected = Prompt.ask(
            "[bold blue]Выберите номер релиза[/bold blue]", choices=[str(i) for i in range(1, len(tag_choices) + 1)]
        )
        tag_name = tag_choices[int(selected) - 1]

        if not Confirm.ask(f"[yellow]🔁 Подтвердите установку релиза {tag_name}[/yellow]"):
            return

        console.print(f"[cyan]📥 Клонируем релиз {tag_name} во временную папку...[/cyan]")
        subprocess.run(["rm", "-rf", TEMP_DIR])
        subprocess.run(f"git clone --depth 1 --branch {tag_name} {GITHUB_REPO} {TEMP_DIR}", shell=True, check=True)

        subprocess.run(["sudo", "rm", "-rf", os.path.join(PROJECT_DIR, "venv")])
        clean_project_dir_safe()

        subprocess.run(f"rsync -a --exclude=img --exclude=handlers/buttons.py {TEMP_DIR}/ {PROJECT_DIR}/", shell=True)
        subprocess.run(["rm", "-rf", TEMP_DIR])

        install_dependencies()
        restart_service()
        console.print(f"[green]✅ Обновление до релиза {tag_name} завершено.[/green]")

    except Exception as e:
        console.print(f"[red]❌ Ошибка при обновлении: {e}[/red]")


def show_update_menu():
    table = Table(title="Выберите способ обновления", title_style="bold green")
    table.add_column("№", justify="center", style="cyan", no_wrap=True)
    table.add_column("Источник", style="white")
    table.add_row("1", "Обновить до BETA")
    table.add_row("2", "Обновить до последнего релиза")
    table.add_row("3", "Назад в меню")

    console.print(table)
    choice = Prompt.ask("[bold blue]Введите номер[/bold blue]", choices=["1", "2", "3"])

    if choice == "1":
        update_from_beta()
    elif choice == "2":
        update_from_release()


def show_menu():
    table = Table(title="Solobot CLI v0.1.4", title_style="bold magenta", header_style="bold blue")
    table.add_column("№", justify="center", style="cyan", no_wrap=True)
    table.add_column("Операция", style="white")
    table.add_row("1", "Запустить бота (systemd)")
    table.add_row("2", "Запустить напрямую: venv/bin/python main.py")
    table.add_row("3", "Перезапустить бота (systemd)")
    table.add_row("4", "Остановить бота (systemd)")
    table.add_row("5", "Показать логи (80 строк)")
    table.add_row("6", "Показать статус")
    table.add_row("7", "Обновить Solobot")
    table.add_row("8", "Выход")
    console.print(table)


def main():
    os.chdir(PROJECT_DIR)
    print_logo()
    try:
        while True:
            show_menu()
            choice = Prompt.ask("[bold blue]Введите номер действия[/bold blue]", choices=[str(i) for i in range(1, 9)])
            if choice == "1":
                if is_service_exists(SERVICE_NAME):
                    subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "2":
                if Confirm.ask("[green]Вы действительно хотите запустить main.py вручную?[/green]"):
                    subprocess.run(["venv/bin/python", "main.py"])
            elif choice == "3":
                if is_service_exists(SERVICE_NAME):
                    if Confirm.ask("[yellow]Вы действительно хотите перезапустить бота?[/yellow]"):
                        subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "4":
                if is_service_exists(SERVICE_NAME):
                    if Confirm.ask("[red]Вы уверены, что хотите остановить бота?[/red]"):
                        subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME])
                else:
                    console.print(f"[red]❌ Служба {SERVICE_NAME} не найдена.[/red]")
            elif choice == "5":
                if is_service_exists(SERVICE_NAME):
                    subprocess.run(["sudo", "journalctl", "-u", SERVICE_NAME, "-n", "80", "--no-pager"])
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
                console.print("[bold cyan]Выход из CLI. Удачного дня![/bold cyan]")
                break
    except KeyboardInterrupt:
        console.print("\n[bold red]⏹ Прерывание. Выход из CLI.[/bold red]")


if __name__ == "__main__":
    main()
