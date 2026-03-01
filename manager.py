import typer
import questionary
import json
import subprocess
import pyperclip
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

app = typer.Typer(help="Manage accounts and launch them in incognito mode.")
console = Console()

DB_FILE = Path.home() / ".tenant_accounts.json"

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
    url: str = typer.Option("http://localhost:3000/login", prompt="Login URL", help="The URL to open for this account")
):
    db = load_db()
    
    if alias in db:
        overwrite = typer.confirm(f"Alias '{alias}' already exists. Overwrite?")
        if not overwrite:
            raise typer.Abort()

    db[alias] = {
        "email": email,
        "password": password,
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
    
    pyperclip.copy(account["password"])
    
    info_panel = Panel(
        f"[bold]Alias:[/bold] {selected}\n"
        f"[bold]Email:[/bold] {account['email']}\n"
        f"[bold]URL:[/bold] {account['url']}\n\n"
        f"[bold green]✔ Password copied to clipboard! (Ready to paste)[/bold green]",
        title="Account Launched",
        border_style="green",
        expand=False
    )
    console.print(info_panel)
    
    open_incognito(account["url"])

if __name__ == "__main__":
    app()