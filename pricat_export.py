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

def generate_pricat(data, filename="pricat.edi"):
    """Generate an EDIFACT PRICAT message and save to a file."""
    
    try:
        validate_data(data)
    except ValueError as e:
        logging.error(e)
        return ""

    logging.info("Generating PRICAT message...")
    
    edifact = [
        "UNA:+.? '",  # Service string advice
        f"UNH+{data['message_ref']}+PRICAT:D:96A:UN'"
    ]
    
    edifact.append(f"BGM+{data['doc_code']}+{data['doc_number']}+9'")
    current_date = datetime.datetime.now().strftime('%Y%m%d')
    edifact.append(f"DTM+137:{current_date}:102'")
    currency = data.get("currency", "EUR")
    edifact.append(f"CUX+2:{currency}:9'")
    
    # Reference (RFF)
    edifact.append(f"RFF+ON:{data['doc_number']}'")
    
    for party in data['parties']:
        if "qualifier" not in party or "id" not in party:
            logging.warning("Skipping invalid NAD entry: %s", party)
            continue
        edifact.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
    
    total_amount = 0.0
    for index, item in enumerate(data['items'], start=1):
        if "product_code" not in item or "description" not in item or "price" not in item:
            logging.warning("Skipping item due to missing fields: %s", item)
            continue
        edifact.append(f"LIN+{index}++{item['product_code']}:EN'")
        edifact.append(f"IMD+F++:::{item['description']}'")
        edifact.append(f"PRI+AAA:{item['price']}:UP'")
        edifact.append(f"PRI+AAB:{item['price']}:UP'")
        total_amount += float(item['price'])
    
    # Monetary Amount (MOA) - Total price
    edifact.append(f"MOA+86:{total_amount:.2f}:EUR'")
    
    segment_count = len(edifact) - 1
    edifact.append(f"UNT+{segment_count}+{data['message_ref']}'")
    
    edifact_message = "\n".join(edifact)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(edifact_message)
    
    logging.info("PRICAT message generated and saved to %s", filename)
    return edifact_message

# Example data
pricat_data = {
    "message_ref": "123456",
    "doc_code": "9",
    "doc_number": "PRICAT001",
    "currency": "USD",
    "parties": [
        {"qualifier": "BY", "id": "123456789"},
        {"qualifier": "SU", "id": "987654321"}
    ],
    "items": [
        {"product_code": "ABC123", "description": "Product A", "price": "100.00"},
        {"product_code": "XYZ456", "description": "Product B", "price": "200.50"}
    ]
}

# Generate and save PRICAT
pricat_message = generate_pricat(pricat_data)
if pricat_message:
    print("\nGenerated PRICAT Message:\n")
    print(pricat_message)

