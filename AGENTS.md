# Aegis V4 — Pure SMC Strategy

## Overview
Aegis V4 adalah crypto trading bot berbasis **Smart Money Concepts (SMC)** murni.  
Tidak ada scoring system, tidak ada threshold buatan — hanya **price action + market structure**.

## Core Philosophy
| Aturan | Deskripsi |
|--------|-----------|
| **SMC-only** | Entry berdasarkan CHOCH + BOS + FVG + OB konfluensi. Tidak ada indikator tambahan. |
| **Limit order di FVG** | Entry hanya via limit order di FVG midpoint. Tidak ada market order entry. |
| **1:4 RR minimum** | Setiap setup wajib memiliki Risk-to-Reward minimal 1:4. |
| **Multi-TF confluence** | 15m untuk market structure, 1m untuk execution. Minimal 3/5 faktor confluence. |
| **FVG freshness** | Hanya trade FVG yang belum termitigasi (price belum masuk gap). |
| **Once in position: hold to SL/TP** | Tidak ada trailing, tidak ada partial exit. Hanya SL atau TP. |
| **No doubt** | Entry sudah divalidasi, sekarang hold sampai SL/TP. |

## Confluence Factors (6 faktor)
| # | Faktor | Sumber | Sifat |
|---|--------|--------|-------|
| 1 | 15M struktur shift (CHOCH/BOS) | 15m | Wajib (1 atau 2) |
| 2 | 1M CHOCH alignment | 1m | Wajib (1 atau 2) |
| 3 | 1M FVG fresh (belum mitigated) | 1m | Wajib |
| 4 | Order Block proximity (dalam 2× ATR) | 15m | Konfirmasi |
| 5 | Breakout candle (impulsive + volume) | 1m | Konfirmasi |
| 6 | Liquidity Sweep (harga menyapu swing sebelumnya + reversal) | 1m | Wajib |

Aturan kelulusan:
- **Wajib**: Structure shift (faktor 1 ATAU 2) + FVG fresh (#3) + Liquidity Sweep (#6)
- **Minimal**: 3 dari 6 faktor total
- Semua setup yang lolos pasti punya structure shift + FVG + liquidity sweep

## Risk Management
| Parameter | Value |
|-----------|-------|
| RR Target | 1:3 |
| SL | Di belakang swing point terdekat (liquidity inflection) + **1.5× ATR Buffer** |
| TP | 3× risk dari entry |
| Position | Limit order di FVG midpoint |

## Pairs
Pair kripto utama dan aset sintetik di Hyperliquid:
- BTC/USDC:USDC
- ETH/USDC:USDC
- BNB/USDC:USDC
- SOL/USDC:USDC
- HYPE/USDC:USDC
- XRP/USDC:USDC
- LINK/USDC:USDC
- SPX/USDC:USDC (S&P 500)
- MKTS-GOLD/USDC:USDC (Emas)
- MKTS-AAPL/USDC:USDC (Apple)
- MKTS-NVDA/USDC:USDC (NVIDIA)
- XRP/USDC:USDC
- LINK/USDC:USDC

## File Structure
```
aegis/
├── analysis/          # SMC scanner
├── strategy/          # SMC strategy class
├── indicators.py      # SMC indicator functions (CHOCH, FVG, OB, BOS, etc.)
├── config.py          # SMC symbols & positions
├── execution.py       # Order execution via CCXT
├── db.py              # OHLCV cache
├── journals/          # Trading journal
└── aegis_config.json  # Exchange & SMC config
```

## Commands
```bash
# Full SMC scan (5 pair, 15m+1m)
./venv/bin/python3 analysis/scan_smc.py
```

## Don'ts
- **JANGAN** menambah indikator (RSI, MACD, EMA, Bollinger, dll) — SMC murni.
- **JANGAN** membuat "scoring" atau threshold buatan.
- **JANGAN** market entry — selalu limit order di FVG.
- **JANGAN** mengubah RR target < 1:3.
- **JANGAN** menyentuh file `.env` atau credential.
- **JANGAN** trailing atau partial exit — hold to SL/TP.
