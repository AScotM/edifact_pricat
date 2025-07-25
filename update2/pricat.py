#!/usr/bin/env python3
import datetime
import logging
import os
import re
from typing import List, Dict, Any, Optional, Tuple, Set
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Setup logger
logger = logging.getLogger(__name__)
log_level = os.getenv("PRICAT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pricat_generator.log")
    ]
)

# EDIFACT Constants
UNA_SEGMENT = "UNA:+.? '"
SEG_SEPARATOR = "'"
ESCAPE_CHAR = "?"  # Not fully implemented (EDIFACT escaping is context-sensitive)

VALID_CURRENCIES: Set[str] = {"EUR", "USD", "GBP", "JPY"}
VALID_QUALIFIERS: Set[str] = {"BY", "SU", "SE"}

class PRICATValidationError(ValueError):
    """Custom exception for PRICAT validation errors."""
    pass

def escape_edifact(text: str) -> str:
    """Escape EDIFACT reserved characters in text."""
    return text.replace("'", "?+")

def validate_price(price: Any) -> Decimal:
    try:
        price_decimal = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price_decimal < 0:
            raise PRICATValidationError("Price cannot be negative")
        return price_decimal
    except (InvalidOperation, TypeError) as e:
        raise PRICATValidationError(f"Invalid price value: {price}") from e

def validate_data(
    data: Dict[str, Any],
    valid_qualifiers: Set[str] = VALID_QUALIFIERS,
    valid_currencies: Set[str] = VALID_CURRENCIES
) -> None:
    required_fields = {
        "message_ref": str,
        "doc_code": str,
        "doc_number": str,
        "parties": list,
        "items": list,
        "edifact_version": str
    }

    for field, field_type in required_fields.items():
        if field not in data:
            raise PRICATValidationError(f"Missing required field: {field}")
        if not isinstance(data[field], field_type):
            raise PRICATValidationError(f"Field {field} must be {field_type.__name__}")
        if field_type == list and not data[field]:
            raise PRICATValidationError(f"Field {field} cannot be empty")

    edifact_version = data["edifact_version"].upper()
    if not re.match(r"^[A-Z]:\d{2}[A-Z]:UN$", edifact_version):
        raise PRICATValidationError("Invalid EDIFACT version format")

    currency = data.get("currency", "EUR")
    if currency not in valid_currencies:
        raise PRICATValidationError(f"Invalid currency code: {currency}. Must be one of {valid_currencies}")

    for party in data["parties"]:
        if not all(k in party for k in ("qualifier", "id")):
            raise PRICATValidationError("Each party must have 'qualifier' and 'id'")
        if party["qualifier"] not in valid_qualifiers:
            raise PRICATValidationError(f"Invalid party qualifier: {party['qualifier']}")
        if not isinstance(party["id"], str) or not party["id"]:
            raise PRICATValidationError("Party ID must be a non-empty string")

    for item in data["items"]:
        if not all(k in item for k in ("product_code", "description", "price")):
            raise PRICATValidationError("Each item requires product_code, description, and price")
        if not isinstance(item["product_code"], str) or not item["product_code"]:
            raise PRICATValidationError("Product code must be a non-empty string")
        if not isinstance(item["description"], str) or not item["description"]:
            raise PRICATValidationError("Description must be a non-empty string")
        validate_price(item["price"])
        if "quantity" in item:
            if not isinstance(item["quantity"], (int, float)) or item["quantity"] <= 0:
                raise PRICATValidationError("Quantity must be a positive number")

def generate_edi_segments(data: Dict[str, Any], strict: bool = False) -> Tuple[List[str], Decimal, int]:
    segments = [
        UNA_SEGMENT,
        f"UNH+{data['message_ref']}+PRICAT:{data['edifact_version'].upper()}'",
        f"BGM+{data['doc_code']}+{data['doc_number']}+9'",
        f"DTM+137:{datetime.datetime.now().strftime('%Y%m%d')}:102'",
        f"CUX+2:{data.get('currency', 'EUR')}:9'",
        f"RFF+ON:{data['doc_number']}'"
    ]
    
    for party in data['parties']:
        segments.append(f"NAD+{party['qualifier']}+{party['id']}::91'")
        logger.debug("Added party segment: NAD+%s+%s::91", party['qualifier'], party['id'])

    total_amount = Decimal("0.00")
    item_count = 0

    for index, item in enumerate(data['items'], start=1):
        try:
            price = validate_price(item["price"])
            description = escape_edifact(item["description"])

            segments.extend([
                f"LIN+{index}++{item['product_code']}:EN'",
                f"IMD+F++:::{description}'",
                f"PRI+AAA:{price:.2f}:UP'",
                f"PRI+AAB:{price:.2f}:UP'"
            ])

            if "quantity" in item:
                unit = item.get("unit", "PCE")
                segments.append(f"QTY+47:{item['quantity']}:{unit}'")
                logger.debug("Added quantity segment for item %d: %s", index, item['product_code'])

            total_amount += price
            item_count += 1
            logger.debug("Added item %d: %s, price: %.2f", index, item['product_code'], price)

        except (KeyError, PRICATValidationError) as e:
            logger.warning("Invalid item %d (%s): %s", index, item.get('product_code', 'unknown'), e)
            if strict:
                raise PRICATValidationError(f"Invalid item {index}: {e}")
            continue

    return segments, total_amount, item_count

def generate_pricat(data: Dict[str, Any], filename: Optional[str] = "pricat.edi", overwrite: bool = False) -> str:
    try:
        validate_data(data)
        segments, total_amount, item_count = generate_edi_segments(data)

        currency = data.get("currency", "EUR")
        segments.extend([
            f"MOA+86:{total_amount:.2f}:{currency}'",
            f"UNT+{len(segments) - 1}+{data['message_ref']}'"
        ])

        edifact_message = "\n".join(segments)

        if filename:
            if os.path.exists(filename) and not overwrite:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                base, ext = os.path.splitext(filename)
                filename = f"{base}_{timestamp}{ext}"
                logger.info("File exists, using new filename: %s", filename)

            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(edifact_message)
                logger.info("PRICAT saved to %s", filename)
            except OSError as e:
                logger.error("File write error: %s", e)
                raise

        logger.info("Generated PRICAT with %d items, total %.2f %s", item_count, total_amount, currency)
        return edifact_message

    except PRICATValidationError as e:
        logger.error("Validation failed: %s", e)
        return ""
    except Exception as e:
        logger.exception("Unexpected error generating PRICAT: %s", e)
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
            {"product_code": "P1001", "description": "Product 1", "price": "125.99", "quantity": 10, "unit": "PCE"},
            {"product_code": "P1002", "description": "Product 2", "price": "89.50", "quantity": 5},
            {"product_code": "P1003", "description": "Product 3", "price": "45.25"}
        ]
    }

    edi_message = generate_pricat(pricat_data, "output/output.edi", overwrite=False)
    if edi_message:
        print("Generated PRICAT:")
        print(edi_message)
