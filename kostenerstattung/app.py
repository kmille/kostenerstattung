import logging
from functools import wraps
from datetime import datetime
from flask_bootstrap import Bootstrap5
from markupsafe import escape
import waitress
from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory
import argon2

from kostenerstattung.config import load_config
config = load_config()
if config["debug"]:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("urllib").setLevel(logging.INFO)
logging.getLogger("alembic").setLevel(logging.WARNING)

from flask_migrate import Migrate
from kostenerstattung.utils import save_belege, get_belege, generate_ticket_data, get_version, generate_qrcode, delete_belege_dir, get_version
from kostenerstattung.forms import ErstattungEinreichenFormular, ErstattungAendernFormular, VerbuchungsFormular, LoginForm, ErstattungLoeschenForm, BezahlungsFormular, WeblingReloadForm

app = Flask(__name__)
app.secret_key = config["secret_key"]
app.config["SQLALCHEMY_DATABASE_URI"] = config["db"]
app.config['PERMANENT_SESSION_LIFETIME'] = 60*60*24*7 # 7 days

from kostenerstattung.models import db, ErstattungsState, TableErstattung
# TOOD: create db dir if not exists
logging.info(f"Using database: {config["db"]}")
db.init_app(app)
migrate = Migrate(app, db)

app.config['BOOTSTRAP_SERVE_LOCAL'] = True
bootstrap = Bootstrap5(app)

error_counter = 0

with app.app_context():
    db.create_all()
    logging.info("Database is empty. Created database schema. TODO: what?")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin", False):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/", methods=["GET", "POST"])
def index():
    form = ErstattungEinreichenFormular()
    if form.validate_on_submit():
        form_data = {field.name: field.data for field in form if field.name not in ("csrf_token", "belege", "cache_in_browser", "submit")}
        erstattung = TableErstattung(**form_data)
        erstattung.state = ErstattungsState.NEW
        db.session.add(erstattung)
        db.session.commit()
        save_belege(config["upload_dir"], erstattung.id, form.belege)
        flash("Das Formular wurde erfolgreich abgeschickt.", "success")
        logging.info(f"Saved new Erstattung to databases ({erstattung})")

        try:
            url_erstattung = config["hostname_base_url"] + url_for('show_erstattung', erstattung_id=erstattung.id)
            body = generate_ticket_data(url_erstattung, form)
            # TODO: optimize that
            belege = get_belege(config["upload_dir"], erstattung.id, b64encoded=True)
            ticket_id, ticket_number = config["zammad_api"].create_ticket(form.name.data, form.email.data, body, belege)
            erstattung.ticket_id = ticket_id
            erstattung.ticket_number = ticket_number
            db.session.commit()
        except Exception as e:
            global error_counter
            error_counter += 1
            logging.error(f"Could create ticket for Erstattung: {e}")
        return redirect(url_for("index"))
    return render_template("create_erstattung.html", form=form)


@app.route("/erstattungen")
@login_required
def list_erstattungen():
    #page = request.args.get('page', 1, type=int)
    #pagination = TableErstattung.query.filter_by(state=ErstattungsState.NEW).paginate(page=page, per_page=10)
    #pagination = TableErstattung.query.paginate(page=page, per_page=10)
    #erstattungen = pagination.items
    erstattungen = TableErstattung.query.all()
    titles = [("id", "#"), ("created_at", "Eingereicht"), ("name", "Name"), ("description", "Beschreibung"), ("betrag", "Betrag")]
    data_neu = []
    data_bezahlt = []
    data_verbucht = []
    for e in erstattungen:
        row = {"id": e.id, "created_at": e.created_at.strftime("%d.%m.%Y (%a) %H:%M"), "name": e.name, "description": e.description[:300], "betrag": e.betrag}
        if e.state == ErstattungsState.NEW:
            data_neu.append(row)
        elif e.state == ErstattungsState.PAID:
            data_bezahlt.append(row)
        else:
            data_verbucht.append(row)
    return render_template("list_erstattungen.html", titles=titles, data_neu=data_neu, data_bezahlt=data_bezahlt, data_verbucht=data_verbucht)


@app.route("/erstattung/<int:erstattung_id>/belege/<path:beleg_name>")
@login_required
def show_beleg(erstattung_id, beleg_name):
    _ = db.get_or_404(TableErstattung, erstattung_id)
    return send_from_directory(config["upload_dir"] / str(erstattung_id), beleg_name)


@app.route("/erstattung/<int:erstattung_id>/anzeigen")
@login_required
def show_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)
    belege = get_belege(config["upload_dir"], erstattung_id)
    return render_template("show_erstattung.html", erstattung=erstattung, belege=belege)


@app.route("/erstattung/<int:erstattung_id>/bearbeiten", methods=["GET", "POST"])
@login_required
def edit_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if erstattung.verwendungszweck:
        flash("Diese Kostenerstattung wurde schon bezahlt. Sie kann daher nicht mehr bearbeitet werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    ef = ErstattungAendernFormular(request.form, obj=erstattung)
    if ef.validate_on_submit():
        ef.populate_obj(erstattung)
        db.session.commit()
        flash("Die Kostenerstattung wurde aktualisiert.", "success")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))
    return render_template("edit_erstattung.html", erstattung=erstattung, form=ef)


@app.route("/erstattung/<int:erstattung_id>/bezahlen", methods=["GET", "POST"])
@login_required
def pay_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if erstattung.booked_at:
        flash("Diese Kostenerstattung wurde schon verbucht und darf nicht nochmal überwiesen werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    belege = get_belege(config["upload_dir"], erstattung_id)
    qrcode = None

    form = BezahlungsFormular()
    if request.method == "GET" and erstattung.verwendungszweck:
        qrcode = generate_qrcode(erstattung.verwendungszweck,
                                 erstattung.iban,
                                 erstattung.betrag,
                                 erstattung.name_bank_account)
    if form.validate_on_submit():
        erstattung.state = ErstattungsState.PAID
        erstattung.paid_at = datetime.now()
        erstattung.verwendungszweck = form.verwendungszweck.data
        db.session.commit()
        config["zammad_api"].add_tag(erstattung.ticket_id, config["zammad"]["tag_payed"])
        if form.benachrichtigung.data:
            config["zammad_api"].create_article(erstattung.ticket_id,
                                                "RAZ - Deine Kostenerstattung/eingereichte Rechnung wurde überwiesen",
                                                f"Hallo {erstattung.name},\nWir haben dir eben {erstattung.betrag} Euro überwiesen.\nDein Geld sollte normalerweise spätestens morgen auf dem angegebenen Konto sein.\n\nViele Grüße\nDie Finanz AG",
                                                erstattung.email)
            flash(f"{erstattung.name} wurde über das Ticketsystem informiert, dass das Geld überwiesen wurde.", "success")
        qrcode = generate_qrcode(form.verwendungszweck.data,
                                 erstattung.iban,
                                 erstattung.betrag,
                                 erstattung.name_bank_account)
    return render_template("pay_erstattung.html",
                           form=form,
                           erstattung=erstattung,
                           belege=belege,
                           qrcode=qrcode)

#    if request.method == "GET":
#        buchungs_periode_id = int(request.args.get("buchungsperiode", config["webling"]["default_buchungsperiode_id"]))
#        vf = VerbuchungsFormular(obj=erstattung)
#        #vf.buchungsperiode.choices = [(x.id, str(x)) for x in w.buchungsperioden]
#        #vf.buchungsperiode.default = buchungs_periode_id
#        #vf.buchungsperiode.process([])
#        try:
#            vf.buchungskonto.choices = [(x.id, x.name) for x in w.data[buchungs_periode_id]["buchungskonten"]]
#            vf.kostenstelle.choices = [(x.id, x.name) for x in w.data[buchungs_periode_id]["kostenstellen"]]
#        except Exception as e:
#            logging.exception(e)
#        return render_template("pay_erstattung.html", form=vf, erstattung=erstattung, belege=belege)
#    vf = VerbuchungsFormular()
#    if vf.validate_on_submit():
#        # todo: ValueError
#        epc_qr = consumer_epc_qr(
#            beneficiary=vf.verwendungszweck.data,
#            iban=erstattung.iban,
#            amount=erstattung.betrag,
#            remittance=erstattung.name_bank_account
#        )
#        data = epc_qr.to_qr(inline=True)
#
#        vf.populate_obj(erstattung)
#        erstattung.state = ErstattungsState.PAID
#        #erstattung.buchungskonto_id = int(vf.buchungskonto.data)
#        db.session.commit()
#        config["zammad_api"].add_tag(erstattung.ticket_id, config["zammad"]["tag_payed"])
#
#        flash("Person wurde benachrichtigt")
#        flash("Ticket hat Tag bekommen")
#        flash("Kostenstelle/Kostenart gespeichert")


@app.route("/erstattung/<int:erstattung_id>/verbuchen", methods=["GET", "POST"])
@login_required
def book_erstattung(erstattung_id):
    erstattung = db.get_or_404(TableErstattung, erstattung_id)

    if not erstattung.verwendungszweck:
        flash("Die Erstattung wurde noch nicht bezahlt und kann daher noch nicht verbucht werden.", "error")
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))

    form = VerbuchungsFormular(request.form, obj=erstattung)
    if form.validate_on_submit():
        erstattung.state = ErstattungsState.BOOKED
        erstattung.booked_at = datetime.now()
        erstattung.buchungsperiode_id = int(form.buchungsperiode.data)
        erstattung.kostenstelle_id = int(form.kostenstelle.data)
        erstattung.buchungskonto_soll_id = int(form.buchungskonto_soll.data)
        erstattung.buchungskonto_haben_id = int(form.buchungskonto_haben.data)
        db.session.commit()
        flash("Die Erstattung wurde erfolgreich verbucht.", "success")
        #config["zammad_api"].add_tag(erstattung.ticket_id, config["zammad"]["tag_payed"])
        return redirect(url_for("show_erstattung", erstattung_id=erstattung.id))
    else:
        #form = VerbuchungsFormular(obj=erstattung)
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
        belege = get_belege(config["upload_dir"], erstattung_id)
        return render_template("book_erstattung.html",
                               form=form,
                               erstattung=erstattung,
                               belege=belege)


@app.route("/erstattung/<int:erstattung_id>/loeschen", methods=["GET", "POST"])
@login_required
def delete_erstattung(erstattung_id):
    # TODO: bug: die Tabelle macht gleich den POST... deswegen  hats oben auch das CSRF gebraucht...
    erstattung = db.get_or_404(TableErstattung, erstattung_id)
    form = ErstattungLoeschenForm()
    if form.validate_on_submit():
        delete_belege_dir(config["upload_dir"], erstattung.id)
        db.session.delete(erstattung)
        db.session.commit()
        flash("Die Erstattung wurde gelöscht.", "success")
        return redirect(url_for("list_erstattungen"))
    return render_template("delete_erstattung.html", erstattung=erstattung, form=form)


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
            logging.error(f"The entered password is wrong: {e}")
    return render_template("login.html", form=form)


@app.errorhandler(404)
def handle_bad_request(e):
    return render_template("400.html"), 404


@app.errorhandler(500)
def handle_server_error(e):
    global error_counter
    logging.error(f"Got an exception: {e}")
    logging.exception(e.original_exception)
    error_counter += 1
    return render_template("500.html", exception=e.original_exception), 500


@app.route("/status")
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
