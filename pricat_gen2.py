import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def validate_data(data):
    """Validate required fields in PRICAT data."""
    required_fields = ["message_ref", "doc_code", "doc_number", "parties", "items"]
    
    for field in required_fields:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(data["items"], list) or len(data["items"]) == 0:
        raise ValueError("PRICAT must contain at least one item.")

    logging.info("Data validation passed.")

def format_price(price):
    """Ensure price is formatted correctly as a float with two decimals."""
    try:
        return f"{float(price):.2f}"
    except ValueError:
        raise ValueError(f"Invalid price format: {price}")

def generate_pricat(data):
    """Generate an EDIFACT PRICAT message from structured data."""
    
    try:
        validate_data(data)  # Validate input data
    except ValueError as e:
        logging.error(e)
        return ""

    logging.info("Generating PRICAT message...")

    # UNH - Message Header
    edifact = [
        "UNA:+.? '",  # Service string advice
        f"UNH+{data['message_ref']}+PRICAT:D:96A:UN'"
    ]
    logging.info("Added UNH segment.")

    # BGM - Beginning of Message
    edifact.append(f"BGM+{data['doc_code']}+{data['doc_number']}+9'")
    logging.info("Added BGM segment.")

    # DTM - Date/Time
    current_date = datetime.datetime.now().strftime('%Y%m%d')
    edifact.append(f"DTM+137:{current_date}:102'")
    logging.info("Added DTM segment with date: %s", current_date)

    # CUX - Currency (Example: EUR)
    currency = data.get("currency", "EUR")  # Default to EUR if not provided
    edifact.append(f"CUX+2:{currency}:9'")
    logging.info("Added CUX segment with currency: %s", currency)

    # NAD - Party Information
    for party in data['parties']:
        if "qualifier" not in party or "id" not in party:
            logging.warning("Skipping invalid NAD entry: %s", party)
            continue  # Skip invalid parties

        edifact.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
        logging.info("Added NAD segment for %s", party["qualifier"])

    # LIN - Line Items
    for index, item in enumerate(data['items'], start=1):
        if "product_code" not in item or "description" not in item or "price" not in item:
            logging.warning("Skipping invalid item: %s", item)
            continue

        edifact.append(f"LIN+{index}++{item['product_code']}:EN'")
        edifact.append(f"IMD+F++::: {item['description']}'")

        try:
            price = format_price(item['price'])
            edifact.append(f"PRI+AAA:{price}:UP'")  # AAA = Net price
            edifact.append(f"PRI+AAB:{price}:UP'")  # AAB = Gross price
        except ValueError as e:
            logging.error(e)
            continue  # Skip invalid price

        logging.info("Added LIN segment for item %d: %s", index, item["product_code"])

    # UNT - Message Trailer
    segment_count = len(edifact) - 1  # Excluding UNA
    edifact.append(f"UNT+{segment_count}+{data['message_ref']}'")
    logging.info("Added UNT segment with segment count: %d", segment_count)

    logging.info("PRICAT message generated successfully.")
    return "\n".join(edifact)

# Example structured data
pricat_data = {
    "message_ref": "123456",
    "doc_code": "9",
    "doc_number": "PRICAT001",
    "currency": "USD",
    "parties": [
        {"qualifier": "BY", "id": "123456789"},  # Buyer
        {"qualifier": "SU", "id": "987654321"}   # Supplier
    ],
    "items": [
        {"product_code": "ABC123", "description": "Product A", "price": "100.00"},
        {"product_code": "XYZ456", "description": "Product B", "price": "200.50"},
        {"product_code": "INVALID", "description": "Invalid Item"}  # Missing price (should be skipped)
    ]
}

# Generate PRICAT Message
pricat_message = generate_pricat(pricat_data)
if pricat_message:
    print("\nGenerated PRICAT Message:\n")
    print(pricat_message)

