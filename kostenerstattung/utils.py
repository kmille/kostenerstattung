from datetime import datetime
from pathlib import Path
from base64 import b64encode
import shutil
import magic
from werkzeug.utils import secure_filename

from py_epc_qr.transaction import consumer_epc_qr

import logging


def save_belege(upload_dir: Path, erstattung_id: int, belege):
    try:
        target_dir = upload_dir / str(erstattung_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        for beleg in belege.data:
            logging.debug(f"Saving Beleg {beleg.filename} of Erstattung {erstattung_id} to {target_dir}")
            out_file = (target_dir / secure_filename(beleg.filename)).as_posix()
            beleg.save(out_file)
    except Exception as e:
        raise Exception(f"Could not save Belege to disk: {e}") from e


def get_belege(upload_dir: Path, erstattung_id: int, b64encoded=False):
    # TODO: needs comment
    try:
        target_dir = upload_dir / str(erstattung_id)
        for file in target_dir.iterdir():
            if b64encoded:
                file_content = file.read_bytes()
                mime_type = magic.from_buffer(file_content, mime=True)
                yield (file.name, mime_type, b64encode(file_content).decode())
            else:
                yield file
    except Exception as e:
        raise Exception(f"Could not read Belege from disk: {e}") from e


def delete_belege_dir(upload_dir: Path, erstattung_id: int, b64encoded=False):
    try:
        target_dir = upload_dir / str(erstattung_id)
        shutil.rmtree(target_dir)
    except Exception as e:
        raise Exception(f"Could not delete Belege from disk: {e}") from e


def generate_ticket_data(url_erstattung: str, form: str) -> str:
    out = f"""Es gibt eine neue Kostenerstattung:\n
{form.name.label.text}: {form.name.data}
{form.email.label.text}: {form.email.data}
Vor- und Nachname Kontoinhaber*in: {form.name_bank_account.data}
{form.iban.label.text}: {form.iban.data}
{form.betrag.label.text}: {form.betrag.data}
{form.description.label.text}\n{form.description.data}

Eingereicht am {datetime.now().strftime("%d.%m.%Y %H:%M")}
Link zur Buchhaltung: {url_erstattung}"""
    return out


def generate_qrcode(verwendungszweck: str, iban: str, betrag: float, name_bank_account: str) -> bytes:
    try:
        epc_qr = consumer_epc_qr(
            beneficiary=name_bank_account,
            iban=iban,
            amount=betrag,
            remittance=verwendungszweck
        )
        return epc_qr.to_qr(inline=True)
    except Exception as e:
        raise Exception(f"Could not generate payment qr code: {e}") from e


def get_version():
    from importlib.metadata import version
    v = version("kostenerstattung")
    return f"v{v}"


def generate_password_hash():
    from argon2 import PasswordHasher
    from secrets import token_hex
    password = token_hex(16)
    pw_hash = PasswordHasher().hash(password)
    print(f"Password: {password}\nHash: {pw_hash}")


if __name__ == '__main__':
    generate_password_hash()
