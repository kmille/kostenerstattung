import sys
import os
import yaml
import logging
from pathlib import Path
import requests.exceptions

from kostenerstattung.zammad import Zammad
from kostenerstattung.webling import Webling


def load_config() -> dict:
    # TODO: error handling
    try:
        config_file = Path.cwd() / "config.yml"
        if "CONFIG_FILE" in os.environ:
            config_file = Path(os.environ["CONFIG_FILE"])
        logging.info(f"Loading config {config_file.absolute()}")
        with config_file.open() as f:
            config = yaml.safe_load(f)
        upload_dir = Path(config["upload_directory"])
        if not upload_dir.exists():
            upload_dir.mkdir()
        config["upload_dir"] = upload_dir
        config["zammad_api"] = Zammad(config["zammad"]["api_base_url"],
                                      config["zammad"]["api_key"],
                                      config["zammad"]["group"])

        config["webling_api"] = Webling(config["webling"]["base_url"],
                                        config["webling"]["api_key"])
        return config
    except Exception as e:
        logging.exception(f"Could not load config file: {e}")
        sys.exit(1)
