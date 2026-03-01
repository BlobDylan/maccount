import typer
import questionary
import json
import subprocess
import pyperclip
import base64
import os
import tomllib
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

app = typer.Typer(help="Manage accounts and launch them in incognito mode.")
console = Console()

DB_FILE = Path.home() / ".tenant_accounts.json"

KDF_ITERATIONS = 390000


def get_cli_version() -> str:
    pyproject_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_file.exists():
        try:
            with open(pyproject_file, "rb") as f:
                project_data = tomllib.load(f)
            return project_data["project"]["version"]
        except (KeyError, OSError, tomllib.TOMLDecodeError):
            pass

    try:
        return package_version("cybr-tenant-cli")
    except PackageNotFoundError:
        return "unknown"


def version_callback(value: bool):
    if value:
        console.print(f"maccount {get_cli_version()}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show CLI version and exit",
        callback=version_callback,
        is_eager=True,
    )
):
    pass


def derive_fernet_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def encrypt_password(password: str, master_password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    key = derive_fernet_key(master_password, salt)
    encrypted_password = Fernet(key).encrypt(password.encode("utf-8")).decode("utf-8")
    return encrypted_password, base64.b64encode(salt).decode("utf-8")


def decrypt_password(encrypted_password: str, master_password: str, salt_b64: str) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    key = derive_fernet_key(master_password, salt)
    return Fernet(key).decrypt(encrypted_password.encode("utf-8")).decode("utf-8")

def load_db() -> dict:
    if not DB_FILE.exists():
        return {}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_db(data: dict):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def open_incognito(url: str):
    try:
        subprocess.run(["open", "-na", "Prisma Access Browser", "--args", "--incognito", url])
    except Exception as e:
        console.print(f"[bold red]Failed to open browser automatically: {e}[/bold red]")
        console.print(f"Please open this URL manually: {url}")

@app.command()
def add(
    alias: str = typer.Option(..., prompt="Account Alias (e.g., admin-user)", help="A short name to identify this account"),
    email: str = typer.Option(..., prompt="Email/Username"),
    password: str = typer.Option(..., prompt="Password", hide_input=True),
    master_password: str = typer.Option(..., prompt="Master Password", hide_input=True, confirmation_prompt=True),
    url: str = typer.Option("", prompt="Login URL", help="The URL to open for this account")
):
    db = load_db()
    
    if alias in db:
        overwrite = typer.confirm(f"Alias '{alias}' already exists. Overwrite?")
        if not overwrite:
            raise typer.Abort()

    encrypted_password, salt = encrypt_password(password, master_password)

    db[alias] = {
        "email": email,
        "password_encrypted": encrypted_password,
        "salt": salt,
        "url": url
    }
    
    save_db(db)
    console.print(f"[bold green]✔ Account '{alias}' saved successfully![/bold green]")

@app.command(name="list")
def list_accounts():
    db = load_db()
    
    if not db:
        console.print("[yellow]No accounts found. Use 'python manager.py add' to create one.[/yellow]")
        return

    table = Table(title="Accounts", border_style="cyan")
    table.add_column("Alias", style="bold cyan")
    table.add_column("Email", style="green")
    table.add_column("Password", style="dim")
    table.add_column("URL", style="blue")

    for alias, data in db.items():
        table.add_row(
            alias, 
            data["email"], 
            "********", 
            data["url"]
        )

    console.print(table)

@app.command()
def delete():
    db = load_db()
    
    if not db:
        console.print("[yellow]No accounts to delete.[/yellow]")
        return

    choices = list(db.keys()) + ["Cancel"]
    selected = questionary.select("Select account to delete:", choices=choices, pointer="❯").ask()

    if selected == "Cancel" or selected is None:
        return

    del db[selected]
    save_db(db)
    console.print(f"[bold red]✔ Account '{selected}' deleted.[/bold red]")

@app.command(name="open")
def launch_account():
    db = load_db()
    
    if not db:
        console.print("[yellow]No accounts found. Use 'add' first.[/yellow]")
        return

    choices = list(db.keys()) + ["Cancel"]
    selected = questionary.select("Select account to launch:", choices=choices, pointer="❯").ask()

    if selected == "Cancel" or selected is None:
        return

    account = db[selected]

    if "password_encrypted" not in account or "salt" not in account:
        console.print(
            "[bold red]This account uses legacy plaintext password storage.[/bold red]"
        )
        console.print(
            "[yellow]Delete and re-add this account to enable master-password encryption.[/yellow]"
        )
        return

    master_password = typer.prompt("Master Password", hide_input=True)

    try:
        decrypted_password = decrypt_password(
            account["password_encrypted"],
            master_password,
            account["salt"],
        )
    except (InvalidToken, ValueError):
        console.print("[bold red]Master password is incorrect.[/bold red]")
        return

    pyperclip.copy(account["email"])
    open_incognito(account["url"])

    info_panel = Panel(
        f"[bold]Alias:[/bold] {selected}\n"
        f"[bold]Email:[/bold] {account['email']}\n\n"
        f"[bold green]✔ Email copied to clipboard![/bold green]\n"
        f"Press Enter when you're ready to copy the password.",
        title="Account Launched",
        border_style="green",
        expand=False
    )
    console.print(info_panel)

    input()

    pyperclip.copy(decrypted_password)
    console.print("[bold green]✔ Password copied to clipboard. Exiting.[/bold green]")
    return

if __name__ == "__main__":
    app()