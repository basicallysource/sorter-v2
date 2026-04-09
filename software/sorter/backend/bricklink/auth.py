import os
from requests_oauthlib import OAuth1

BL_CONSUMER_KEY = os.environ.get("BL_CONSUMER_KEY", "")
BL_CONSUMER_SECRET = os.environ.get("BL_CONSUMER_SECRET", "")
BL_TOKEN_VALUE = os.environ.get("BL_TOKEN_VALUE", "")
BL_TOKEN_SECRET = os.environ.get("BL_TOKEN_SECRET", "")


def getAuth() -> OAuth1:
    return OAuth1(BL_CONSUMER_KEY, BL_CONSUMER_SECRET, BL_TOKEN_VALUE, BL_TOKEN_SECRET)
