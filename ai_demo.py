from ai import extract_intent_from_text
from netpay.extract import parse_intent

if __name__ == "__main__":

    print("\nNETPAY AI\n")

    user_text = input("Enter request:\n\n")

    result = extract_intent_from_text(user_text)

    print("\nAI Output\n")
    print(result)

    intent = parse_intent(result)

    print("\nValidated Intent\n")
    print(intent)