import requests
from dataclasses import dataclass
from typing import List
from datetime import date, datetime
from base64 import b64encode
import json

import requests.exceptions

from kostenerstattung.utils import get_version

import logging


class Buchungsperiode:
    def __init__(self, _id: str, api_data: dict):
        self.id = _id
        self.name = api_data["title"]
        self._from = datetime.strptime(api_data["from"], "%Y-%m-%d").date()
        self.to = datetime.strptime(api_data["to"], "%Y-%m-%d").date()

    def __repr__(self):
        return f"{self.name} ({self._from.strftime("%d.%m.%Y")} - {self.to.strftime("%d.%m.%Y")})"


class Buchungskonto:
    def __init__(self, api_data: dict):
        self.id = api_data["id"]
        self.name = api_data['properties']["title"]

    def __repr__(self):
        return f"{self.name}"


class Kostenstelle:
    def __init__(self, api_data: dict):
        self.id = api_data["id"]
        self.name = api_data['properties']["title"]

    def __repr__(self):
        return f"{self.name}"


class Webling:

    def __init__(self, base_url: str, api_key: str):
        logging.info("Loading Webling configuration via API")
        self.api_base_url = base_url + "/api/1"
        self.session = requests.Session()
        self.session.headers.update({"apikey": api_key,
                                     "User-Agent": f"Kobu {get_version}"})

        self.buchungsperioden = self._get_buchungsperioden()
        self.data = {}
        #bp_tmp = [x for x in self.buchungsperioden if x.id == 15328][0]
        #for buchungsperiode in [bp_tmp, ]:
        #for buchungsperiode in self.buchungsperioden[:1]:
        for buchungsperiode in self.buchungsperioden:
            buchungskonten = self._get_buchungskonten(buchungsperiode.id)
            kostenstellen = self._get_kostenstellen(buchungsperiode.id)
            self.data[buchungsperiode.id] = {}
            self.data[buchungsperiode.id]["buchungskonten"] = buchungskonten
            self.data[buchungsperiode.id]["kostenstellen"] = kostenstellen
        self.lastschriften = self.get_unverbuchte_lastschriften()

    def _get_buchungsperioden(self):
        logging.info("Loading Buchungsperioden from Webling API")
        try:
            resp = self.session.get(self.api_base_url + "/period/", params="format=full")
            resp.raise_for_status()
            buchungsperioden = []
            for data in resp.json():
                buchungsperioden.append(Buchungsperiode(data["id"], data["properties"]))
            return buchungsperioden
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not load Buchungsperioden from Webling API") from e

    def _get_buchungskonten(self, buchungsperiode_id: int):
        logging.info(f"Loading Buchungskonten for Buchungsperiode {buchungsperiode_id} from Webling API")
        try:
            resp = self.session.get(self.api_base_url + "/account", params=f"filter=$parents.$parents.$id={buchungsperiode_id}&format=full")
            resp.raise_for_status()
            buchungskonten = []
            for data in resp.json():
                buchungskonten.append(Buchungskonto(data))
            return buchungskonten
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not load Buchungskonten from Webling API") from e

    def _get_kostenstellen(self, buchungsperiode_id: int):
        logging.info(f"Loading Kostenstellen for Buchungsperiode {buchungsperiode_id} from Webling API")
        try:
            resp = self.session.get(self.api_base_url + "/costcenter", params=f"filter=$parents.$id={buchungsperiode_id}&format=full")
            resp.raise_for_status()
            kostenstellen = []
            for data in resp.json():
                kostenstellen.append(Kostenstelle(data))
            return kostenstellen
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not load Kostenstellen from Webling API") from e

    def get_unverbuchte_lastschriften(self):
        logging.info("Loading unverbuchte Lastschriften (current year) from Webling API")
        try:
            # resp = session.get(BASE_URL + "/payment", params="filter=amount=500")
            # resp = session.get(BASE_URL + "/payment", params="format=full&filter=`processed` IS EMPTY")
            resp = self.session.get(self.api_base_url + "/payment", params="filter=`processed` != 'processed'&format=full")
            resp.raise_for_status()
            payments = []
            for payment in resp.json():
                payment_date = datetime.strptime(payment["properties"]["date"], "%Y-%m-%d")
                if payment_date.year == datetime.now().date().year:
                    payments.append(payment)
            return payments
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not load Lastschriften from Webling API") from e

    def get_buchungs_id(self, entrygroup_id: int) -> int:
        # entrygroup_id is a unique internal id of a Buchung
        # the returned entry id is the one shown in the web UI (unique for Buchungsperiode)
        try:
            resp = self.session.get(self.api_base_url + f"/entrygroup/{entrygroup_id}")
            resp.raise_for_status()
            return resp.json()["properties"]["entryid"]
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not get Buchungs-ID for Webling Buchung from Webling API") from e

    def create_buchung(self, erstattung, payment_id, beleg):
        logging.debug("Creating Buchung in Webling")
        data = {
            "properties": {
                "date": erstattung.paid_at.date().isoformat(),
                "title": erstattung.verwendungszweck,
            },
            "children": {
                "entry": [
                    {
                        "properties": {
                            "amount": abs(erstattung.betrag),
                            "receipt": f"#{erstattung.ticket_number}",
                            "isEBill": False,
                        },
                        "links": {
                            "debit": [erstattung.buchungskonto_soll_id],
                            "credit": [erstattung.buchungskonto_haben_id],
                            "costcenter": [erstattung.kostenstelle_id],
                            "payment": [payment_id],
                        }
                    }
                ]
            },
            "parents": [erstattung.buchungsperiode_id]
        }

        logging.debug(f"Create Buchung request body:\n{json.dumps(data, indent=4)}")

        if beleg:
            filename, beleg_data = beleg
            attachment = {
                "receiptfile": {
                    "name": filename,
                    "content": b64encode(beleg_data).decode()
                }
            }
            data["children"]["entry"][0]["properties"].update(attachment)

        try:
            resp = self.session.post(self.api_base_url + "/entrygroup", json=data)
            resp.raise_for_status()
            logging.debug(f"Created Buchung:{resp.text}")
            # just the entry/Buchungs-ID
            return resp.text
        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError):
                logging.error(f"Webling API response: {e.response.text}")
            raise Exception("Could not create new Buchung via Webling API") from e


def print_webling_data():
    from kostenerstattung.config import load_config
    webling = load_config()["webling_api"]
    print("Buchungsperioden")
    for buchungsperiode in webling.buchungsperioden:
        print(f"{buchungsperiode.id} | {str(buchungsperiode)}")
    for buchungsperiode in webling.buchungsperioden:
        print(f"Buchungsperiode: {buchungsperiode.id} | {buchungsperiode}")
        data = webling.data[buchungsperiode.id]
        print("Buchungskonten")
        for buchungskonto in data["buchungskonten"]:
            print(f"- {buchungskonto.id} {buchungskonto}")
        print("Kostenstellen")
        for kostenstelle in data["kostenstellen"]:
            print(f"- {kostenstelle.id} {kostenstelle}")


#if __name__ == '__main__':
#    Webling()
