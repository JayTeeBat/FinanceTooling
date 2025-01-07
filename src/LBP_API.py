import os
import requests
import json
import logging
from pprint import pprint

LOCAL_FOLDER = os.path.dirname(os.path.abspath(__file__))
CLIENT_TOKEN_FILE = os.path.join(LOCAL_FOLDER, "client_token.txt")
USER_TOKEN_FILE = os.path.join(LOCAL_FOLDER, "user_token.txt")


class API:
    endpoint_url = r"https://api.labanquepostale.com/sandbox"

    client_id = "3270293245"
    client_secret = "885930"

    def __init__(self, config_file=None):
        self.logger = logging.getLogger(__name__)
        self.client_token = ""
        self.user_token = ""
        self.load_token()

    def load_token(self):
        """
        Loading client and user token from file
        """
        try:
            with open(CLIENT_TOKEN_FILE, "r") as f:
                self.client_token = f.read()
        except FileNotFoundError:
            self.refresh_client_token()

        # try:
        #     with open(USER_TOKEN_FILE, "r") as f:
        #         self.user_token = f.read()
        # except FileNotFoundError:
        #     self.refresh_user_token()

    def refresh_client_token(self):
        """
        Refresh potentially expired client_token
        """
        token_url = self.endpoint_url + "/token"
        response = requests.request(
            "post",
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if response.status_code > 300:
            raise RequestException(response)
        else:
            data = json.loads(response.content.decode("utf-8"))
            self.client_token = data["access_token"]
            with open(CLIENT_TOKEN_FILE, "w") as f:
                f.write(self.client_token)

    def refresh_user_token(self):
        """
        Refresh potentially expired client_token
        """
        token_url = self.endpoint_url + "/authz/oauth2/token"
        response = requests.request(
            "post",
            token_url,
            data={
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            },
        )
        if response.status_code > 300:
            raise RequestException(response)
        else:
            data = json.loads(response.content.decode("utf-8"))
            self.user_token = data["access_token"]
            with open(USER_TOKEN_FILE, "w") as f:
                f.write(self.user_token)


class RequestException(BaseException):
    """
    Handling exceptions in httprequests
    """

    def __init__(self, response: requests.Response):
        pprint(json.loads(response.content.decode()))
        raise Exception(response)
