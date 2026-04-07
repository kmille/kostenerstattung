import sys
import json
import logging
from functools import wraps
from datetime import datetime
from flask_bootstrap import Bootstrap5
import waitress
from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory, abort
from markupsafe import Markup
import argon2

from kostenerstattung.config import load_config
config = load_config()
if config["debug"]:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("urllib").setLevel(logging.INFO)
logging.getLogger("alembic").setLevel(logging.WARNING)

from flask_migrate import Migrate
from kostenerstattung.utils import save_belege, get_belege, generate_ticket_body_text, get_version, delete_belege_dir
from kostenerstattung.forms import ErstattungEinreichenFormular, ErstattungAendernFormular, VerbuchungsFormular, LoginForm, ErstattungLoeschenForm, BezahlungsFormular, WeblingReloadForm, LastschriftVerbuchungsFormular

app = Flask(__name__)
app.secret_key = config["secret_key"]
app.config["SQLALCHEMY_DATABASE_URI"] = config["db"]
app.config['PERMANENT_SESSION_LIFETIME'] = 60*60*24*7 # 7 days
app.config['SERVER_NAME'] = config["server_name"]

from kostenerstattung.models import db, ErstattungsState, TableErstattung
# TODO: create db dir if not exists
logging.info(f"Using database: {config["db"]}")
db.init_app(app)
migrate = Migrate(app, db)

app.config['BOOTSTRAP_SERVE_LOCAL'] = True
bootstrap = Bootstrap5(app)

error_counter = 0

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        logging.error(f"Could not initialize database: {e}")
        sys.exit(1)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        try:
            ph = argon2.PasswordHasher()
            ph.verify(config["admin_hash"], form.password.data)
            session["admin"] = True
            session.permanent = True
            flash("Du hast dich erfolgreich angmeldet.", "success")
            return redirect(url_for("list_erstattungen"))
        except (ValueError, argon2.exceptions.Argon2Error) as e:
            flash("Das eingegebene Passwort ist falsch.", "error")
            logging.warning(f"The entered password is wrong: {e}")
    return render_template("login.html", form=form)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin", False):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/", methods=["GET", "POST"])
def index():

    def create_erstattung_from_form(form):
        form_data = {field.name: field.data for field in form if field.name not in ("csrf_token", "belege", "cache_in_browser", "submit")}
        form_data["iban"] = form_data["iban"].replace(" ", "")
        erstattung = TableErstattung(**form_data)
        erstattung.state = ErstattungsState.NEW
        db.session.add(erstattung)
        db.session.commit()
        save_belege(config["belege_dir"], erstattung.id, form.belege)
        flash("Das Formular wurde erfolgreich abgeschickt.", "success")
        logging.info(f"Saved new Erstattung to databases ({erstattung})")
        return erstattung

    def create_ticket_for_erstattung(erstattung, form):
        try:
            url_erstattung = url_for("show_erstattung",
                                     erstattung_id=erstattung.id,
                                     _external=True,
                                     _scheme="https")
            body = generate_ticket_body_text(url_erstattung, form)
            subject = erstattung.description[:80]

            # TODO: first we write Beleg to disk, then we read it again
            # form.belege.data[0]
            #   <FileStorage: '2026-03-11-111023_screenshot.png' ('image/png')>
            #   x.filename
            #   x.mimetype
            #   but: can not access the data anymore, as we "consumed" it when writing the Beleg to disc
            belege = get_belege(config["belege_dir"], erstattung.id, b64encoded=True)

            ticket_id, ticket_number = config["zammad_api"].create_ticket(
                form.name.data,
                form.email.data,
                subject,
                body,
                belege
            )
            erstattung.ticket_id = ticket_id
            erstattung.ticket_number = ticket_number
            db.session.commit()
        except Exception:
            global error_counter
            error_counter += 1
            logging.exception("Could not create ticket for Erstattung")

    form = ErstattungEinreichenFormular()
    if not form.validate_on_submit():
        return render_template("create_erstattung.html", form=form)

    erstattung = create_erstattung_from_form(form)
    create_ticket_for_erstattung(erstattung, form)
    return redirect(url_for("index"))


@app.route("/erstattungen")
@login_required
def list_erstattungen():

    def erstattung_to_row(e):
        return {
            "id": e.id,
            "created_at": e.created_at.strftime("%d.%m.%Y (%a) %H:%M"),
            "name": e.name,
            "description": e.description[:300],
            "betrag": e.betrag
        }

    ERSTATTUNG_TABLE_COLUMNS = [
        ("id", "#"),
        ("created_at", "Eingereicht"),
        ("name", "Name"),
        ("description", "Beschreibung"),
        ("betrag", "Betrag")
    ]

    erstattungen_neu = TableErstattung.query.filter_by(state=ErstattungsState.NEW).order_by(TableErstattung.created_at.desc()).all()
    erstattungen_paid = TableErstattung.query.filter_by(state=ErstattungsState.PAID).order_by(TableErstattung.created_at.desc()).all()
    erstattungen_booked = TableErstattung.query.filter_by(state=ErstattungsState.BOOKED).order_by(TableErstattung.created_at.desc()).all()
    erstattungen_done = TableErstattung.query.filter_by(state=ErstattungsState.DONE).order_by(TableErstattung.created_at.desc()).all()

    return render_template(
        "list_erstattungen.html",
        titles=ERSTATTUNG_TABLE_COLUMNS,
        erstattungen_neu=[erstattung_to_row(e) for e in erstattungen_neu],
        erstattungen_paid=[erstattung_to_row(e) for e in erstattungen_paid],
        erstattungen_booked=[erstattung_to_row(e) for e in erstattungen_booked],
        erstattungen_done=[erstattung_to_row(e) for e in erstattungen_done]
    )


@app.route("/erstattung/<int:erstattung_id>/belege/<path:beleg_name>")
@login_required
def show_beleg(erstattung_id, beleg_name):
    _ = db.get_or_404(TableErstattung, erstattung_id)
    return send_from_directory(config["belege_dir"] / str(erstattung_id), beleg_name)


@app.route("/erstattung/<int:erstattung_id>/anzeigen")
@login_required
def show_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)
    belege = get_belege(config["belege_dir"], erstattung_id)
    return render_template("show_erstattung.html", erstattung=erstattung, belege=belege)


@app.route("/erstattung/<int:erstattung_id>/bearbeiten", methods=["GET", "POST"])
@login_required
def edit_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if erstattung.state in (ErstattungsState.PAID, ErstattungsState.BOOKED, ErstattungsState.DONE):
        flash("Diese Kostenerstattung wurde schon bezahlt. Sie kann daher nicht mehr bearbeitet werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    form = ErstattungAendernFormular(obj=erstattung)
    if form.validate_on_submit():
        form.populate_obj(erstattung)
        db.session.commit()
        flash("Die Kostenerstattung wurde aktualisiert.", "success")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))
    return render_template("edit_erstattung.html", erstattung=erstattung, form=form)


@app.route("/erstattung/<int:erstattung_id>/bezahlen", methods=["GET", "POST"])
@login_required
def pay_erstattung(erstattung_id):

    def create_payment_notification():
        subject = "RAZ - Deine Kostenerstattung/eingereichte Rechnung wurde überwiesen"
        body = f"Hallo {erstattung.name},\nWir haben dir eben {erstattung.betrag} Euro überwiesen." \
               "\n\nViele Grüße\nDie Finanz AG"
        config["zammad_api"].create_article(
            erstattung.ticket_id,
            subject,
            body,
            erstattung.email
        )
        flash(f"{erstattung.name} wurde über das Ticketsystem informiert, dass das Geld überwiesen wurde.", "success")

    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if erstattung.state in (ErstattungsState.PAID, ErstattungsState.BOOKED, ErstattungsState.DONE):
        flash("Diese Kostenerstattung wurde schon verbucht und darf nicht nochmal überwiesen werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    belege = get_belege(config["belege_dir"], erstattung_id)
    qrcode = None

    form = BezahlungsFormular()
    if request.method == "GET" and erstattung.state == ErstattungsState.PAID:
        qrcode = erstattung.create_qr_code()
    if form.validate_on_submit():
        erstattung.state = ErstattungsState.PAID
        erstattung.paid_at = datetime.now()
        erstattung.verwendungszweck = form.verwendungszweck.data.strip()
        db.session.commit()
        qrcode = erstattung.create_qr_code()

        try:
            config["zammad_api"].add_tag(erstattung.ticket_id, config["zammad"]["tag_paid"])
            if form.benachrichtigung.data:
                create_payment_notification()
        except Exception:
            global error_counter
            error_counter += 1
            logging.exception("Could not update ticket after creating payment qr code")

    return render_template(
        "pay_erstattung.html",
        form=form,
        erstattung=erstattung,
        belege=belege,
        qrcode=qrcode
    )


def get_pre_filled_verbuchungs_formular(form):
    form.buchungsperiode.choices = [(x.id, str(x)) for x in config["webling_api"].buchungsperioden]

    if config["webling"]["default_buchungskonto_haben_id"]:
        form.buchungskonto_haben.default = int(config["webling"]["default_buchungskonto_haben_id"])
        form.buchungskonto_haben.process([])

    buchungs_periode_id = int(request.args.get("buchungsperiode", int(config["webling"]["default_buchungsperiode_id"])))
    form.buchungsperiode.default = buchungs_periode_id
    form.buchungsperiode.process([])

    form.kostenstelle.choices = [(x.id, x.name) for x in config["webling_api"].data[buchungs_periode_id]["kostenstellen"]]
    form.buchungskonto_soll.choices = [(x.id, x.name) for x in config["webling_api"].data[buchungs_periode_id]["buchungskonten"]]
    form.buchungskonto_haben.choices = [(x.id, x.name) for x in config["webling_api"].data[buchungs_periode_id]["buchungskonten"]]
    return form


@app.route("/erstattung/<int:erstattung_id>/verbuchen", methods=["GET", "POST"])
@login_required
def book_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if erstattung.state == ErstattungsState.NEW:
        flash("Die Erstattung wurde noch nicht bezahlt und kann daher noch nicht verbucht werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    if erstattung.state in (ErstattungsState.BOOKED, ErstattungsState.DONE):
        flash("Die Erstattung wurde bereits verbucht.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    form = VerbuchungsFormular(request.form, obj=erstattung)
    belege = get_belege(config["belege_dir"], erstattung_id)
    if request.method == "GET":
        form = get_pre_filled_verbuchungs_formular(VerbuchungsFormular())
    elif form.validate_on_submit():
        erstattung.state = ErstattungsState.BOOKED
        erstattung.booked_at = datetime.now()
        erstattung.buchungsperiode_id = int(form.buchungsperiode.data)
        erstattung.kostenstelle_id = int(form.kostenstelle.data)
        erstattung.buchungskonto_soll_id = int(form.buchungskonto_soll.data)
        erstattung.buchungskonto_haben_id = int(form.buchungskonto_haben.data)
        db.session.commit()
        flash("Die Erstattung wurde erfolgreich verbucht.", "success")
        #config["zammad_api"].add_tag(erstattung.ticket_id, config["zammad"]["tag_paid"])
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))
    else:
        form = VerbuchungsFormular(obj=erstattung)
    return render_template("book_erstattung.html",
                           form=form,
                           erstattung=erstattung,
                           belege=belege)


@app.route("/erstattung/<int:erstattung_id>/loeschen", methods=["GET", "POST"])
@login_required
def delete_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)
    form = ErstattungLoeschenForm()
    if form.validate_on_submit():
        delete_belege_dir(config["belege_dir"], erstattung.id)
        db.session.delete(erstattung)
        db.session.commit()
        flash("Die Erstattung wurde gelöscht.", "success")
        return redirect(url_for("list_erstattungen"))
    return render_template("delete_erstattung.html", erstattung=erstattung, form=form)


@app.route("/lastschriften")
@login_required
def list_lastschriften():
    titles = [
        ("id", "#"),
        ("created_at", "Datum"),
        ("name", "Name"),
        ("description", "Verwendungszweck"),
        ("betrag", "Betrag")
    ]
    rows = []
    lastschriften = config["webling_api"].lastschriften
    for lastschrift in lastschriften:
        lastschrift_properties = json.loads(lastschrift["properties"]["data"])
        if lastschrift["properties"]["amount"] > 0:
            name = lastschrift_properties.get("extra_payer_information", "")
        else:
            name = lastschrift_properties.get("extra_payee_information", "")

        row = {
            "id": lastschrift["id"],
            "created_at": datetime.strptime(lastschrift["properties"]["date"], "%Y-%m-%d").strftime("%d.%m.%Y"),
            "name": name,
            "description": lastschrift["properties"]["title"],
            "betrag": f"{lastschrift["properties"]["amount"]:.2f}".replace(".", ",")
        }
        rows.append(row)
    rows.sort(key=lambda x: x["id"], reverse=True)
    return render_template(
        "list_lastschriften.html",
        titles=titles,
        rows=rows
    )


@app.route("/lastschrift/<int:lastschrift_id>/verbuchen", methods=["GET", "POST"])
@login_required
def book_lastschrift(lastschrift_id):

    lastschrift = {}
    for lastschrift_iter in config["webling_api"].lastschriften:
        if lastschrift_iter["id"] == lastschrift_id:
            lastschrift = lastschrift_iter
            break
    if lastschrift == {}:
        abort(404, "Die Lastschrift wurde nicht gefunden")

    if request.method == "GET":
        form = get_pre_filled_verbuchungs_formular(LastschriftVerbuchungsFormular())
    else:
        form = LastschriftVerbuchungsFormular()
        if form.validate_on_submit():

            beleg = None
            ticket_number = ""
            if len(form.ticket_number.data) != 0:
                ticket_number = form.ticket_number.data.replace("Ticket", "").replace("#", "")
                beleg = config["zammad_api"].get_concatenated_attachments_from_ticket(ticket_number)

            erstattung = TableErstattung(paid_at=datetime.strptime(lastschrift["properties"]["date"], "%Y-%m-%d"),
                                         verwendungszweck=lastschrift["properties"]["title"],
                                         betrag=lastschrift["properties"]["amount"],
                                         ticket_number=ticket_number,
                                         buchungskonto_soll_id=int(form.buchungskonto_soll.data),
                                         buchungskonto_haben_id=int(form.buchungskonto_haben.data),
                                         kostenstelle_id=int(form.kostenstelle.data),
                                         buchungsperiode_id=int(form.buchungsperiode.data))
            booking_id = config["webling_api"].create_buchung(erstattung, lastschrift["id"], beleg)
            webling_booking_url = f"{config['webling']['base_url']}/admin#/accounting/{config['webling']['default_buchungsperiode_id']}/entrygroup/:entrygroup/editor/{booking_id}"
            html_message = Markup(f'Die Lastschrift wurde erfolgreich in Twingle verbucht (<a href="{webling_booking_url}">link</a>).')
            flash(html_message, "success")

            if len(form.ticket_number.data) != 0:
                ticket_number = "#" + form.ticket_number.data.replace("Ticket", "").replace("#", "")
                ticket_id = config["zammad_api"].get_ticket(ticket_number)["id"]
                config["zammad_api"].remove_tag(ticket_id, config["zammad"]["tag_paid"])
                subject = "Erfolgreich verbucht"
                body = f"Die Erstattung wurde in Webling verbucht: {webling_booking_url}"
                config["zammad_api"].create_article(
                    ticket_id,
                    subject,
                    body
                )

                if form.close_ticket.data:
                    config["zammad_api"].update_state(ticket_id, config["zammad"]["state_closed"])
                    flash(f"Das Ticket (#{ticket_number}) wurde geschlossen.", "success")
                    config["webling_api"].lastschriften.remove(lastschrift)
                return redirect(url_for("list_lastschriften"))
    return render_template("book_lastschrift.html",
                           lastschrift=lastschrift,
                           form=form)


@app.route("/api/v1/ticket/<string:ticket_id>")
@login_required
def get_ticket(ticket_id: str):
    try:
        ticket_id = int(ticket_id.replace("#", "").replace("Ticket", ""))
    except ValueError:
        return {"error": "Ungültige Ticket Nummer"}
    return config["zammad_api"].get_ticket(ticket_id)


@app.route("/api/v1/config/reload", methods=["POST"])
def api_reload_config():
    # no auth, don't return any data
    global config
    config = load_config()
    return "reload succeeded"


@app.route("/config", methods=["GET", "POST"])
@login_required
def reload_config():
    form = WeblingReloadForm()
    if form.validate_on_submit():
        global config
        config = load_config()
        flash("Die Konfiguration wurde neu eingelesen.", "success")
    return render_template("config.html",
                           form=form,
                           version=get_version())


@app.errorhandler(404)
def handle_bad_request(e):
    return render_template("400.html", exception=e), 404


@app.errorhandler(500)
def handle_server_error(e):
    global error_counter
    logging.error(f"{request.method} {request.url}")
    logging.error(f"{request.form.to_dict()}")
    error_counter += 1
    return render_template("500.html", exception=e.original_exception), 500


@app.route("/status", methods=["GET", "POST"])
def status() -> dict:
    if error_counter == 0:
        return {"status": "ok"}
    else:
        return {"status": "failed"}


@app.context_processor
def add_config():
    # make config available in jinja2 templates
    return {"config": config}


def serve_backend():
    listen_host = config["listen_host"]
    listen_port = config["listen_port"]

    logging.info(f"Running Kostenerstattung {get_version()} on {listen_host}:{listen_port} (debug={config['debug']})")
    if __name__ == '__main__':
        app.run(debug=True,
                host=listen_host,
                port=listen_port)
    else:
        waitress.serve(app, listen=f"{listen_host}:{listen_port}")


if __name__ == '__main__':
    serve_backend()
