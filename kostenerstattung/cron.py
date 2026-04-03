import logging
from flask import Flask
from datetime import datetime
import json

logger = logging.getLogger(__name__)
FORMAT = "[%(asctime)s %(levelname)5s] %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)

app = Flask(__name__)
from kostenerstattung.config import load_config
config = load_config()


from kostenerstattung.models import db, ErstattungsState, TableErstattung
app.config["SQLALCHEMY_DATABASE_URI"] = config["db"]
db.init_app(app)

from kostenerstattung.utils import get_belege


def main():
    logger.info("Start Verbuchen in Webling. Looking for paid Erstattungen")
    unbooked_lastschriften = config["webling_api"].get_unverbuchte_lastschriften()
    with app.app_context():
        booked_erstattungen = TableErstattung.query.filter_by(state=ErstattungsState.BOOKED).all()
        for lastschrift in unbooked_lastschriften:
            lastschrift_properties = json.loads(lastschrift["properties"]["data"])
            lastschrift_betrag = lastschrift_properties["amount"]
            if lastschrift_betrag > 0:
                continue
            lastschrift_iban = lastschrift_properties.get("extra_payee")
            #print(json.dumps(lastschrift, indent=4))
            for erstattung in booked_erstattungen:
                if erstattung.id == 4:
                    continue
                if lastschrift_properties["description"].startswith(erstattung.verwendungszweck) and \
                        lastschrift_iban == erstattung.iban and \
                        abs(float(lastschrift_betrag)) == erstattung.betrag:
                    logger.info(f"Match {erstattung} (#{erstattung.ticket_number}) with {lastschrift_properties['description']}")
                    belege = config["zammad_api"].get_concatenated_attachments_from_ticket(erstattung.ticket_number)

                    date_bank = datetime.strptime(lastschrift_properties["made_on"], "%Y-%m-%d").date()
                    if date_bank != erstattung.paid_at.date():
                        logger.warning(f"Date mismatch (bank={date_bank}, erstattet={erstattung.paid_at})")
                        continue

                    entrygroup_id = config["webling_api"].create_buchung(erstattung, lastschrift["id"], belege)
                    booking_id = config["webling_api"].get_buchungs_id(entrygroup_id)

                    webling_booking_url = f"{config['webling']['base_url']}/admin#/accounting/{config['webling']['default_buchungsperiode_id']}/entrygroup/:entrygroup/editor/{entrygroup_id}"
                    subject = "Erfolgreich verbucht"
                    body = f"Die Erstattung wurde in Webling verbucht: {webling_booking_url}"
                    config["zammad_api"].create_article(
                        erstattung.ticket_id,
                        subject,
                        body
                    )
                    config["zammad_api"].remove_tag(erstattung.ticket_id, config["zammad"]["tag_paid"])
                    config["zammad_api"].update_state(erstattung.ticket_id, config["zammad"]["state_closed"])
                    logger.info(f"Die Erstatung {erstattung.id} wurde in Webling verbucht (Buchung #{booking_id}, {webling_booking_url})")

                    erstattung.state = ErstattungsState.DONE
                    erstattung.entrygroup_id = entrygroup_id
                    erstattung.buchungs_id = booking_id
                    db.session.commit()
                    logging.info("Updated Erstattung in db")


"""
PROBLEME:
- Josephine: Name stimmt nicht überein

"""

if __name__ == '__main__':
    main()
