from zammad_py import ZammadAPI
import logging


class Zammad:

    def __init__(self, base_url: str, http_token: str, group: str):
        self.client = ZammadAPI(url=base_url + "/api/v1", http_token=http_token)
        self.group = group

    def _create_customer_if_not_exists(self, name: str, email: str):
        logging.debug(f"Creating customer {name} ({email}) in Zammad")
        try:
            if len(self.client.user.search(email)) > 0:
                logging.debug(f"User with email address {email} already exists")
                return
            else:
                customer_data = {
                    "firstname": name,  # if name has a space, the backend seperates it: first and lastname
                    "email": email,
                    "roles": ["Customer", ],
                }
                customer = self.client.user.create(customer_data)
                logging.debug(f"Successfully creatd customer {name} (email={email}): /#user/profile/{customer['id']}")
        except Exception as e:
            raise Exception(f"Could not check/create customer in Zammad: {e}") from e

    def create_ticket(self, name, email, body, belege):
        logging.debug(f"Creating ticket (email={email})")
        self._create_customer_if_not_exists(name, email)

        params = {
            "title": "Neue Kostenerstattung",
            "group": self.group,
            "customer": email,
            "article": {
                "subject": "Neue Kostenerstattung",
                "body": body,
                "type": "note",
                "internal": False,
                "content_type": "plain/text",
                "attachments": []
            }
        }

        for beleg in belege:
            attachment = {"filename": beleg[0],
                          "mime-type": beleg[1],
                          "data": beleg[2]
                          }
            params["article"]["attachments"].append(attachment)

        """
            for html ticket
                img = \"""<img src="data:image/png;base64,iVBORw0KGgoAAAA....">\"""
                "body": f"I am a message!\n{img}",
                "content_type": "text/html",
        """

        try:
            ticket_data = self.client.ticket.create(params=params)
            ticket_id = ticket_data["id"]
            ticket_number = ticket_data["number"]
            logging.info(f"Successfully created ticket {ticket_id} (#{ticket_number})")
            return ticket_id, ticket_number
        except Exception as e:
            raise Exception(f"Could not create ticket in Zammad: {e}") from e

    def create_article(self, ticket_id: int, subject: str, body: str, to: str = ""):
        logging.debug(f"Creating ticket artickle for ticket {ticket_id} (subject={subject})")
        # https://docs.zammad.org/en/latest/api/ticket/articles.html
        # if to is set, send an email
        params = {
            "ticket_id": ticket_id,
            "subject": subject,
            "body": body,
            "content_type": "text/plain",
            "type": "note",
            "internal": "false",
        }

        if len(to) != 0:
            params["type"] = "email"
            params["to"] = to
        try:
            self.client.ticket_article.create(params=params)
        except Exception as e:
            raise Exception(f"Could not create ticket article in Zammad: {e}") from e

    def add_tag(self, ticket_id: int, tag: str):
        logging.debug(f"Adding tag {tag} to ticket {ticket_id}")
        try:
            self.client.ticket_tag.add(ticket_id, tag)
        except Exception as e:
            raise Exception(f"Could not add tag to ticket in Zammad: {e}") from e

    def remove_tag(self, ticket_id: int, tag: str):
        logging.debug(f"Removing tag {tag} to ticket {ticket_id}")
        try:
            self.client.ticket_tag.remove(ticket_id, tag)
        except Exception as e:
            raise Exception(f"Could not remove tag to ticket in Zammad: {e}") from e

    def update_state(self, ticket_id: int, state: str):
        logging.debug(f"Updating ticket state to {state} to ticket {ticket_id}")
        params = {
            "state": state,
        }
        try:
            self.client.ticket.update(ticket_id, params=params)
        except Exception as e:
            raise Exception(f"Could not update ticket state in Zammad: {e}") from e
