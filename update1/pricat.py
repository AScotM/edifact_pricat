import datetime
import logging
import os
import re
from typing import List, Dict, Any, Optional, Tuple, Set
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

# Valid ISO 4217 currency codes (subset for example)
VALID_CURRENCIES: Set[str] = {"EUR", "USD", "GBP", "JPY"}
# Valid EDIFACT party qualifiers
VALID_QUALIFIERS: Set[str] = {"BY", "SU", "SE"}

def validate_price(price: Any) -> Decimal:
    """Validate and convert price to Decimal.

    Args:
        price: Input price (string, float, or int).

    Returns:
        Decimal: Validated price as a Decimal.

    Raises:
        ValueError: If price is invalid or negative.
    """
    try:
        price_decimal = Decimal(str(price))
        if price_decimal < 0:
            raise ValueError("Price cannot be negative")
        return price_decimal
    except (InvalidOperation, TypeError) as e:
        raise ValueError(f"Invalid price value: {price}") from e

def validate_data(data: Dict[str, Any], valid_qualifiers: Set[str] = VALID_QUALIFIERS, valid_currencies: Set[str] = VALID_CURRENCIES) -> None:
    """Validate PRICAT data structure and content.

    Args:
        data: Dictionary containing PRICAT data.
        valid_qualifiers: Set of allowed party qualifiers (default: {'BY', 'SU', 'SE'}).
        valid_currencies: Set of allowed currency codes (default: {'EUR', 'USD', 'GBP', 'JPY'}).

    Raises:
        ValueError: If validation fails.
    """
    required_fields = {
        "message_ref": str,
        "doc_code": str,
        "doc_number": str,
        "parties": list,
        "items": list,
        "edifact_version": str  # Added for configurable EDIFACT version
    }

    for field, field_type in required_fields.items():
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
        if not isinstance(data[field], field_type):
            raise ValueError(f"Field {field} must be {field_type.__name__}")
        if field_type == list and not data[field]:
            raise ValueError(f"Field {field} cannot be empty")

    # Validate EDIFACT version format (e.g., "D:96A:UN")
    if not re.match(r"^[A-Z]:\d{2}[A-Z]:UN$", data.get("edifact_version", "D:96A:UN")):
        raise ValueError("Invalid EDIFACT version format")

    # Validate currency
    currency = data.get("currency", "EUR")
    if currency not in valid_currencies:
        raise ValueError(f"Invalid currency code: {currency}. Must be one of {valid_currencies}")

    for party in data["parties"]:
        if not all(k in party for k in ("qualifier", "id")):
            raise ValueError("Each party must have 'qualifier' and 'id'")
        if party["qualifier"] not in valid_qualifiers:
            raise ValueError(f"Invalid party qualifier: {party['qualifier']}. Must be one of {valid_qualifiers}")
        if not isinstance(party["id"], str) or not party["id"]:
            raise ValueError("Party ID must be a non-empty string")

    for item in data["items"]:
        if not all(k in item for k in ("product_code", "description", "price")):
            raise ValueError("Each item requires product_code, description, and price")
        if not isinstance(item["product_code"], str) or not item["product_code"]:
            raise ValueError("Product code must be a non-empty string")
        if not isinstance(item["description"], str) or not item["description"]:
            raise ValueError("Description must be a non-empty string")
        validate_price(item["price"])
        # Validate optional quantity if present
        if "quantity" in item:
            if not isinstance(item["quantity"], (int, float)) or item["quantity"] <= 0:
                raise ValueError("Quantity must be a positive number")

def generate_edi_segments(data: Dict[str, Any], strict: bool = False) -> Tuple[List[str], Decimal, int]:
    """Generate EDIFACT segments and calculate totals.

    Args:
        data: Dictionary containing PRICAT data.
        strict: If True, raise an exception on invalid items instead of skipping (default: False).

    Returns:
        Tuple[List[str], Decimal, int]: List of EDIFACT segments, total amount, and item count.

    Raises:
        ValueError: If strict=True and an item is invalid.
    """
    segments = [
        "UNA:+.? '",
        f"UNH+{data['message_ref']}+PRICAT:{data.get('edifact_version', 'D:96A:UN')}'",
        f"BGM+{data['doc_code']}+{data['doc_number']}+9'",
        f"DTM+137:{datetime.datetime.now().strftime('%Y%m%d')}:102'",
        f"CUX+2:{data.get('currency', 'EUR')}:9'",
        f"RFF+ON:{data['doc_number']}'"
    ]
    
    for party in data['parties']:
        segments.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
        logging.debug("Added party segment: NAD+%s+%s::91", party['qualifier'], party['id'])
    
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
            
            # Add optional quantity segment
            if "quantity" in item:
                segments.append(f"QTY+47:{item['quantity']}:PCE'")
                logging.debug("Added quantity segment for item %d: %s", index, item['product_code'])
            
            total_amount += price
            item_count += 1
            logging.debug("Added item %d: %s, price: %.2f", index, item['product_code'], price)
            
        except (KeyError, ValueError) as e:
            logging.warning("Invalid item %d (%s): %s", index, item.get('product_code', 'unknown'), e)
            if strict:
                raise ValueError(f"Invalid item {index} ({item.get('product_code', 'unknown')}): {e}")
            continue
    
    return segments, total_amount, item_count

def generate_pricat(data: Dict[str, Any], filename: Optional[str] = "pricat.edi", overwrite: bool = False) -> str:
    """Generate and optionally save an EDIFACT PRICAT message.

    Args:
        data: Dictionary containing PRICAT data.
        filename: Output file path (default: 'pricat.edi'). If None, no file is written.
        overwrite: If True, overwrite existing file; otherwise, append timestamp (default: False).

    Returns:
        str: Generated EDIFACT message or empty string on error.

    Raises:
        ValueError: If validation fails.
        OSError: If file writing fails.
    """
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
            # Handle file overwrite
            if os.path.exists(filename) and not overwrite:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                base, ext = os.path.splitext(filename)
                filename = f"{base}_{timestamp}{ext}"
                logging.info("File exists, using new filename: %s", filename)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            
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
        logging.exception("Unexpected error generating PRICAT: %s", e)
        return ""

if __name__ == "__main__":
    pricat_data = {
        "message_ref": "MSG123",
        "doc_code": "9",
        "doc_number": "PRICAT2023",
        "currency": "EUR",
        "edifact_version": "D:96A:UN",
        "parties": [
            {"qualifier": "BY", "id": "BUYER001"},
            {"qualifier": "SU", "id": "SUPPLIER001"}
        ],
        "items": [
            {"product_code": "P1001", "description": "Product 1", "price": "125.99", "quantity": 10},
            {"product_code": "P1002", "description": "Product 2", "price": "89.50", "quantity": 5},
            {"product_code": "P1003", "description": "Product 3", "price": "45.25"}
        ]
    }

    edi_message = generate_pricat(pricat_data, "output/output.edi", overwrite=False)
    if edi_message:
        print("Generated PRICAT:")
        print(edi_message)
