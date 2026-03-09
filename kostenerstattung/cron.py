import logging
from flask import Flask

app = Flask(__name__)
from kostenerstattung.config import load_config
config = load_config()

logger = logging.getLogger(__name__)
FORMAT = "[%(asctime)s %(levelname)5s] %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)

from kostenerstattung.models import db, ErstattungsState, TableErstattung
app.config["SQLALCHEMY_DATABASE_URI"] = config["db"]
db.init_app(app)

from kostenerstattung.utils import get_belege


def main():
    logging.info("Start Verbuchen in Webling. Looking for paid Erstattungen")
    with app.app_context():
        booked_erstattungen = TableErstattung.query.filter_by(state=ErstattungsState.BOOKED).all()
        for erstattung in booked_erstattungen:
            logging.info(f"Doing {erstattung}")
            # TODO: abgleichen mit "überweisung ohne Buchung"
            belege = list(get_belege(config["belege_dir"], erstattung.id, b64encoded=True))[0]
            entrygroup_id = config["webling_api"].create_buchung(erstattung, belege)
            buchungs_id = config["webling_api"].get_buchungs_id(entrygroup_id)
            logging.info(f"Die Erstatung {erstattung.id} wurde in Webling verbucht (Buchung {buchungs_id})")
            print(f"Die Erstatung {erstattung.id} wurde in Webling verbucht (Buchung {buchungs_id})")
            #erstattung.state = ErstattungsState.DONE
            erstattung.entrygroup_id = entrygroup_id
            erstattung.buchungs_id = buchungs_id
            db.session.commit()


if __name__ == '__main__':
    main()
