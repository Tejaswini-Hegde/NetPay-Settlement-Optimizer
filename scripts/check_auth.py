from netpay.config import Settings
from netpay.paypal import PayPalClient

if __name__ == "__main__":
    PayPalClient(Settings.from_env()).check_auth()
    print("OK: sandbox authentication works")