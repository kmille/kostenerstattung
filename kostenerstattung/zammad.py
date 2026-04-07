from zammad_py import ZammadAPI
import logging
import requests
from pathlib import Path
from tempfile import TemporaryDirectory
from pypdf import PdfWriter
import img2pdf
from io import BytesIO


class Zammad:

    def __init__(self, base_url: str, http_token: str, group: str):
        logging.info("Initializing Zammd API")
        self.group = group
        self.client = ZammadAPI(url=base_url + "/api/v1", http_token=http_token)
        try:
            self.client.user.me()
        except Exception as e:
            raise Exception(f"Could not initialize Zammad: {e}")

    def _create_customer_if_not_exists(self, name: str, email: str) -> None:
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
                logging.debug(f"Successfully created customer {name} (email={email}): /#user/profile/{customer['id']}")
        except Exception as e:
            raise Exception(f"Could not check/create customer in Zammad ({name} | {email}") from e

    def create_ticket(self, name, email, subject, body, belege):
        logging.debug(f"Creating ticket for {name} ({email} | {subject})")

        params = {
            "title": subject,
            "group": self.group,
            "customer": email,
            "article": {
                "subject": subject,
                "body": body,
                "type": "note",
                "internal": False,
                "content_type": "plain/text",
                "attachments": []
            }
        }

        for beleg in belege:
            attachment = {
                "filename": beleg[0],
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
            self._create_customer_if_not_exists(name, email)
            ticket_data = self.client.ticket.create(params=params)
            ticket_id = ticket_data["id"]
            ticket_number = ticket_data["number"]
            logging.info(f"Successfully created ticket {ticket_id} (#{ticket_number})")
            return ticket_id, ticket_number
        except Exception as e:
            raise Exception("Could not create ticket in Zammad") from e

    def create_article(self, ticket_id: int, subject: str, body: str, to: str = ""):
        logging.debug(f"Creating ticket article for ticket {ticket_id} (subject={subject})")
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
            raise Exception("Could not create ticket article in Zammad") from e

    def add_tag(self, ticket_id: int, tag: str):
        logging.debug(f"Adding tag {tag} to ticket {ticket_id}")
        try:
            self.client.ticket_tag.add(ticket_id, tag)
        except Exception as e:
            raise Exception("Could not add tag to ticket in Zammad") from e

    def remove_tag(self, ticket_id: int, tag: str):
        logging.debug(f"Removing tag {tag} to ticket {ticket_id}")
        try:
            self.client.ticket_tag.remove(ticket_id, tag)
        except Exception as e:
            raise Exception("Could not remove tag to ticket in Zammad") from e

    def update_state(self, ticket_id: int, state: str):
        logging.debug(f"Updating ticket state to '{state}' to ticket {ticket_id}")
        params = {
            "state": state,
        }
        try:
            self.client.ticket.update(ticket_id, params=params)
        except Exception as e:
            raise Exception("Could not update ticket state in Zammad") from e

    def get_ticket(self, ticket_number: int) -> dict:
        logging.debug(f"Searching for ticket: {ticket_number}")
        try:
            tickets = self.client.ticket.search(f"number:{ticket_number}")
            if len(tickets) == 0:
                return {}
            return tickets[0]
        except Exception as e:
            raise Exception("Could not search for tickets in Zammad") from e

    def _get_ticket_attachments(self, ticket_number: int):
        try:
            ticket_id = self.get_ticket(ticket_number)["id"]
            article = self.client.ticket.articles(ticket_id)[0]

            for attachment in article["attachments"]:
                attachment_id = attachment["id"]
                filename = attachment["filename"]

                data = self.client.ticket_article_attachment.download(ticket_id=ticket_id,
                                                                      article_id=article["id"],
                                                                      id=attachment_id)
                yield filename, data
        except Exception as e:
            raise Exception(f"Could not get attachments from ticket {ticket_number}") from e

    def get_concatenated_attachments_from_ticket(self, ticket_number: int):
        logging.info(f"Concatening attachments of ticket {ticket_number}")
        attachments = list(self._get_ticket_attachments(ticket_number))

        # message body is also an attachment (at least sometimes)
        for index, attachment in enumerate(attachments):
            if attachment[0] == 'message.html':
                del attachments[index]

        if len(attachments) == 1:
            return attachments[0]

        with TemporaryDirectory() as tmp:
            # 1) Write Zammad attachment to tmp dir (small file ending)
            for filename_str, data in attachments:
                filename = Path(filename_str)
                out_file = tmp / Path(filename.stem + filename.suffix.lower())
                logging.info(f"Writing ticket attachment to {out_file}")
                out_file.write_bytes(data)

            # 2) Convert images to pdf
            for file in Path(tmp).iterdir():
                if file.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    logging.info(f"Converting {file.name} from img to pdf")
                    #ocrmypdf.ocr(file, (tmp / Path(file.name + ".pdf")), image_dpi=300)
                    pdf = img2pdf.convert(file, rotation=img2pdf.Rotation.ifvalid)
                    (tmp / Path(file.name + ".pdf")).write_bytes(pdf)

            # 3) Iterate over all PDFs and concat them
            buf = BytesIO()
            with PdfWriter() as writer:
                for file in Path(tmp).glob("*.pdf"):
                    writer.append(file)
                writer.write(buf)
            return "Belege.pdf", buf.getvalue()

            #logging.info("Running ocr")
            #ocrmypdf.ocr(out_file,
            #             out_file,
            #             lang=["deu", "eng"], skip_text=True)
