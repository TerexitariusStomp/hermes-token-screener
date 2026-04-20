"""
Protocol-specific contract interaction module.
Provides smart contract interaction patterns for DEXes, bridges, lending, and other protocols.
"""

from .catalog import (
    ProtocolType,
    ContractRole,
    ContractMethod,
    ProtocolTemplate,
    ProtocolCatalog,
    catalog,
)
from .registry import ProtocolDefinition, ProtocolRegistry, registry
from .contract import ProtocolContract
from .classifier import (
    ContractClassifier,
    ContractClassification,
    CATEGORY_MAPPING,
    METHOD_SELECTORS,
)

__all__ = [
    # Types
    "ProtocolType",
    "ContractRole",
    "ContractMethod",
    "ProtocolTemplate",
    "ProtocolDefinition",
    "ContractClassification",
    # Singletons
    "catalog",
    "registry",
    # Classes
    "ProtocolCatalog",
    "ProtocolRegistry",
    "ProtocolContract",
    "ContractClassifier",
    # Data
    "CATEGORY_MAPPING",
    "METHOD_SELECTORS",
]
