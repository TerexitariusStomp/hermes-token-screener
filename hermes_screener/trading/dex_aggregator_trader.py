#!/usr/bin/env python3
"""
DEX Aggregator Trading Bot
Uses multiple DEX aggregators for optimal trading across Base and Solana.
"""

import logging
import os
import sys
import time
from decimal import Decimal

import requests
from dotenv import load_dotenv
from eth_account import Account

import atexit
from hermes_screener import tor_config  # noqa: F401
from web3 import Web3