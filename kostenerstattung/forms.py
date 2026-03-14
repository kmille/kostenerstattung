from wtforms import StringField, EmailField, TextAreaField, FloatField, SubmitField, MultipleFileField, SelectField, PasswordField, BooleanField
from flask_wtf import FlaskForm
from wtforms.validators import DataRequired, ValidationError

from schwifty import IBAN
from schwifty.exceptions import SchwiftyException


class BetragField(FloatField):
    # allow 13,12 and 13.12
    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = float(valuelist[0].replace(',', '.'))
            except ValueError:
                self.data = None
                raise ValueError(self.gettext('Kein gültiger Betrag'))


class ErstattungsFormular(FlaskForm):
    # von ErstattungsFormular wird nur geerbt
    name = StringField("Dein (Spitz)Name", validators=[DataRequired()])
    email = EmailField("Deine E-Mail-Adresse (für Rückfragen)", validators=[DataRequired()])
    name_bank_account = StringField("Vor- und Nachname Kontoinhaber*in (muss zur IBAN passen)",
                                    validators=[DataRequired()])
    iban = StringField("IBAN", validators=[DataRequired()])
    description = TextAreaField("Wofür möchtest du dir Kosten erstatten lassen?",
                                validators=[DataRequired()],
                                render_kw={"rows": 5})
    betrag = BetragField("Betrag (Summe in Euro)", validators=[DataRequired()])

    def validate_iban(form, field):
        try:
            iban = IBAN(field.data)
            iban.validate(validate_bban=True)
        except SchwiftyException as e:
            raise ValidationError(e)


class ErstattungEinreichenFormular(ErstattungsFormular):
    def validate_belege(form, belege):
        for beleg in belege.data:
            valid_extensions = ['pdf', 'png', 'jpg', 'jpeg']
            ext = beleg.filename.split(".")[-1].lower()
            if ext not in valid_extensions:
                raise ValidationError(f"Ungültige Dateiendung. Erlaubt sind {valid_extensions}")

    belege = MultipleFileField("Belege/Rechnungen (du kannst auch mehrere Belege gleichzeitig auswählen/hochladen)",
                               validators=[DataRequired()])
    cache_in_browser = BooleanField("Name, E-Mail-Adresse und IBAN für nächstes mal im Browser speichern?", default=True)
    submit = SubmitField("Rechnung/Kostenerstattung einreichen")


class ErstattungAendernFormular(ErstattungsFormular):
    submit = SubmitField("Änderungen speichern")


class BezahlungsFormular(FlaskForm):
    verwendungszweck = StringField("Verwendungszweck", validators=[DataRequired()])
    benachrichtigung = BooleanField("Person benachrichten, dass das Geld überwiesen wurde.", default=True)
    submit = SubmitField("Erstattung bezahlen")


class VerbuchungsFormular(FlaskForm):
    buchungsperiode = SelectField(validate_choice=False)
    kostenstelle = SelectField(validate_choice=False)
    buchungskonto_soll = SelectField("Bezahlt für", validate_choice=False) # fahrtkosten
    buchungskonto_haben = SelectField("Bezahlt aus", validate_choice=False) # bank
    submit = SubmitField("Erstattung verbuchen")


class LastschriftVerbuchungsFormular(VerbuchungsFormular):
    ticket_number = StringField("Ticket Nummer")
    close_ticket = BooleanField("Ticket schließen?")
    submit = SubmitField("Lastschrift verbuchen")


class LoginForm(FlaskForm):
    password = PasswordField("Passwort", validators=[DataRequired()])
    submit = SubmitField("Login")


class ErstattungLoeschenForm(FlaskForm):
    submit = SubmitField("Erstattung wirklich löschen?")


class WeblingReloadForm(FlaskForm):
    submit = SubmitField("Webling Daten abrufen")

    class Meta:
        csrf = False
