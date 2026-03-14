import sys
import os
import yaml
import logging
from pathlib import Path

from kostenerstattung.zammad import Zammad
from kostenerstattung.webling import Webling


def load_config() -> dict:
    config_file = Path.cwd() / "kobu.yml"
    if "CONFIG_FILE" in os.environ:
        config_file = Path(os.environ["CONFIG_FILE"])
    config_file = config_file.expanduser()
    logging.info(f"Loading config {config_file.absolute()}")
    try:
        with config_file.open() as f:
            config = yaml.safe_load(f)
        belege_dir = Path(config["belege_directory"])
        belege_dir.mkdir(parents=True, exist_ok=True)
        config["belege_dir"] = belege_dir
        config["zammad_api"] = Zammad(config["zammad"]["api_base_url"],
                                      config["zammad"]["api_key"],
                                      config["zammad"]["group"])

        config["webling_api"] = Webling(config["webling"]["base_url"],
                                        config["webling"]["api_key"])
        return config
    except Exception as e:
        logging.error(f"Could not load config file: {e}")
        sys.exit(1)


if __name__ == '__main__':
    config = load_config()
    ticket_number = "901108"
    config["zammad_api"].get_concatenated_attachments_from_ticket(ticket_number)
