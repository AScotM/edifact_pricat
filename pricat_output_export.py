import datetime
import logging
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pricat_generator.log")
    ]
)

def validate_price(price: Any) -> Decimal:
    """Validate and convert price to Decimal."""
    try:
        price_decimal = Decimal(str(price))
        if price_decimal < 0:
            raise ValueError("Price cannot be negative")
        return price_decimal
    except (InvalidOperation, TypeError) as e:
        raise ValueError(f"Invalid price value: {price}") from e

def validate_data(data: Dict[str, Any]) -> None:
    """Validate PRICAT data structure and content."""
    required_fields = {
        "message_ref": str,
        "doc_code": str,
        "doc_number": str,
        "parties": list,
        "items": list
    }
    
    for field, field_type in required_fields.items():
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
        if not isinstance(data[field], field_type):
            raise ValueError(f"Field {field} must be {field_type.__name__}")
        if field_type == list and not data[field]:
            raise ValueError(f"Field {field} cannot be empty")

    for party in data["parties"]:
        if not all(k in party for k in ("qualifier", "id")):
            raise ValueError("Each party must have 'qualifier' and 'id'")

    for item in data["items"]:
        if not all(k in item for k in ("product_code", "description", "price")):
            raise ValueError("Each item requires product_code, description and price")
        validate_price(item["price"])

def generate_edi_segments(data: Dict[str, Any]) -> Tuple[List[str], Decimal, int]:
    """Generate EDIFACT segments and calculate totals."""
    segments = [
        "UNA:+.? '",
        f"UNH+{data['message_ref']}+PRICAT:D:96A:UN'",
        f"BGM+{data['doc_code']}+{data['doc_number']}+9'",
        f"DTM+137:{datetime.datetime.now().strftime('%Y%m%d')}:102'",
        f"CUX+2:{data.get('currency', 'EUR')}:9'",
        f"RFF+ON:{data['doc_number']}'"
    ]
    
    for party in data['parties']:
        segments.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
    
    total_amount = Decimal("0.00")
    item_count = 0
    
    for index, item in enumerate(data['items'], start=1):
        try:
            price = validate_price(item["price"])
            
            segments.extend([
                f"LIN+{index}++{item['product_code']}:EN'",
                f"IMD+F++:::{item['description']}'",
                f"PRI+AAA:{price:.2f}:UP'",
                f"PRI+AAB:{price:.2f}:UP'"
            ])
            
            total_amount += price
            item_count += 1
            
        except (KeyError, ValueError) as e:
            logging.warning("Skipping item %d: %s", index, e)
            continue
    
    return segments, total_amount, item_count

def generate_pricat(data: Dict[str, Any], filename: Optional[str] = "pricat.edi") -> str:
    """Generate and optionally save an EDIFACT PRICAT message."""
    try:
        validate_data(data)
        segments, total_amount, item_count = generate_edi_segments(data)
        
        # Add footer segments
        currency = data.get("currency", "EUR")
        segments.extend([
            f"MOA+86:{total_amount:.2f}:{currency}'",
            f"UNT+{len(segments)-1}+{data['message_ref']}'"
        ])
        
        edifact_message = "\n".join(segments)
        
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(edifact_message)
                logging.info("PRICAT saved to %s", filename)
            except OSError as e:
                logging.error("File write error: %s", e)
                raise
        
        logging.info(
            "Generated PRICAT with %d items, total %.2f %s",
            item_count, total_amount, currency
        )
        return edifact_message
        
    except ValueError as e:
        logging.error("Validation failed: %s", e)
        return ""
    except Exception as e:
        logging.exception("Unexpected error generating PRICAT")
        return ""

if __name__ == "__main__":
    pricat_data = {
        "message_ref": "MSG123",
        "doc_code": "9",
        "doc_number": "PRICAT2023",
        "currency": "EUR",
        "parties": [
            {"qualifier": "BY", "id": "BUYER001"},
            {"qualifier": "SU", "id": "SUPPLIER001"}
        ],
        "items": [
            {"product_code": "P1001", "description": "Product 1", "price": "125.99"},
            {"product_code": "P1002", "description": "Product 2", "price": "89.50"},
            {"product_code": "P1003", "description": "Product 3", "price": "45.25"}
        ]
    }

    edi_message = generate_pricat(pricat_data, "output.edi")
    if edi_message:
        print("Generated PRICAT:")
        print(edi_message)
