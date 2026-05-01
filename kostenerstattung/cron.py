import logging
from flask import Flask
from datetime import datetime
import json

logger = logging.getLogger(__name__)

app = Flask(__name__)
from kostenerstattung.config import load_config
config = load_config()
if config["debug"]:
    logger.setLevel(logging.DEBUG)
    logging.getLogger("urllib").setLevel(logging.INFO)


from kostenerstattung.models import db, ErstattungsState, TableErstattung
app.config["SQLALCHEMY_DATABASE_URI"] = config["db"]
db.init_app(app)


def update_ticket(erstattung, webling_booking_url):
    subject = "Erfolgreich verbucht"
    body = f"Die Erstattung wurde in Webling verbucht: {webling_booking_url}"
    config["zammad_api"].create_article(
        erstattung.ticket_id,
        subject,
        body
    )
    config["zammad_api"].remove_tag(erstattung.ticket_id, config["zammad"]["tag_paid"])
    config["zammad_api"].update_state(erstattung.ticket_id, config["zammad"]["state_closed"])
    logger.debug("Updated Erstattung in ticket")


def cron():
    def update_database():
        erstattung.state = ErstattungsState.DONE
        erstattung.entrygroup_id = entrygroup_id
        erstattung.buchungs_id = booking_id
        db.session.commit()
        logger.debug("Updated Erstattung in db")

    logger.info("Starting cron routine to book Webling Erstattungen paid in KoBu")
    unbooked_lastschriften = config["webling_api"].get_unverbuchte_lastschriften()
    with app.app_context():
        booked_erstattungen = TableErstattung.query.filter_by(state=ErstattungsState.BOOKED).all()
        for erstattung in booked_erstattungen:
            logger.info(f"Checking Ersattung {erstattung}")
            for lastschrift in unbooked_lastschriften:
                #print(json.dumps(lastschrift, indent=4))
                lastschrift_properties = json.loads(lastschrift["properties"]["data"])
                lastschrift_iban = lastschrift_properties.get("extra_payee", "").replace(" ", "")
                lastschrift_betrag = lastschrift_properties["amount"]
                if lastschrift_betrag > 0:
                    continue
                if lastschrift_properties["description"].startswith(erstattung.verwendungszweck) and \
                        lastschrift_iban == erstattung.iban.replace(" ", "") and \
                        abs(float(lastschrift_betrag)) == erstattung.betrag:
                    logger.info(f" Match {erstattung} (#{erstattung.ticket_number}) with '{lastschrift_properties['description']}'")

                    date_bank = datetime.strptime(lastschrift_properties["made_on"], "%Y-%m-%d").date()
                    if date_bank != erstattung.paid_at.date():
                        logger.warning(f" Lastschrift: Date mismatch (bank={date_bank}, erstattet={erstattung.paid_at.date()})")
                        if abs((erstattung.paid_at.date() - date_bank).days) < 4:
                            erstattung.paid_at = datetime(date_bank.year, date_bank.month, date_bank.day)
                            logger.info(" Ignoring date mismatch as difference is below 4 day threshold")
                        else:
                            continue

                    belege = config["zammad_api"].get_concatenated_attachments_from_ticket(erstattung.ticket_number)
                    entrygroup_id = config["webling_api"].create_buchung(erstattung, lastschrift["id"], belege)
                    booking_id = config["webling_api"].get_buchungs_id(entrygroup_id)

                    webling_booking_url = f"{config['webling']['base_url']}/admin#/accounting/{config['webling']['default_buchungsperiode_id']}/entrygroup/:entrygroup/editor/{entrygroup_id}"
                    logger.info(f" Die Erstatung {erstattung.id} wurde in Webling verbucht (Buchung #{booking_id}, {webling_booking_url})")
                    update_ticket(erstattung, webling_booking_url)
                    update_database()


if __name__ == '__main__':
    cron()
