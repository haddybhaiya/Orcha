"""Message evidence extraction, prompt injection defense, and multilingual indexing."""

import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from orcha.evidence.models import EvidenceType, MessageEvidence


class MessageEvidenceExtractor:
    """Extracts and indexes financial evidence from multilingual notification messages."""

    # Prompt injection patterns to sanitize/ignore
    _INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions?", re.I),
        re.compile(r"system\s*prompt", re.I),
        re.compile(r"mark\s+the\s+user\s+rich", re.I),
        re.compile(r"you\s+are\s+now", re.I),
        re.compile(r"bypass\s+rules?", re.I),
    ]

    def __init__(self, cache_path: Path | None = None) -> None:
        self._cache_path = self._resolve_cache_path(cache_path)
        self._by_message_id: dict[str, MessageEvidence] = {}
        self._by_user_id: dict[str, list[MessageEvidence]] = defaultdict(list)
        self._by_event_id: dict[str, list[MessageEvidence]] = defaultdict(list)
        self._by_request_id: dict[str, list[MessageEvidence]] = defaultdict(list)
        self._load_cache()

    @staticmethod
    def _resolve_cache_path(custom_path: Path | None) -> Path:
        if custom_path is not None:
            return custom_path
        candidates = [
            Path("code/cache/message_evidence.json"),
            Path("cache/message_evidence.json"),
            Path("../code/cache/message_evidence.json"),
        ]
        for c in candidates:
            if c.is_file():
                return c
        return Path("code/cache/message_evidence.json")

    def _load_cache(self) -> None:
        if not self._cache_path.is_file():
            return
        with open(self._cache_path, encoding="utf-8") as f:
            records = json.load(f)

        for r in records:
            sent_at = datetime.fromisoformat(r["sent_at"]) if r.get("sent_at") else None
            eff_date = date.fromisoformat(r["effective_date"]) if r.get("effective_date") else None
            amt = Decimal(str(r["amount"])) if r.get("amount") is not None else None
            ev_type = EvidenceType(r["evidence_type"])

            cached_evidence = MessageEvidence(
                message_id=r["message_id"],
                user_id=r["user_id"],
                request_id=r.get("request_id"),
                related_event_id=r.get("related_event_id"),
                sent_at=sent_at,
                source_type=r.get("source_type", "sms"),
                evidence_type=ev_type,
                amount=amt,
                additional_amount=(
                    Decimal(str(r["additional_amount"]))
                    if r.get("additional_amount") is not None
                    else None
                ),
                currency=r.get("currency"),
                effective_date=eff_date,
                status=r.get("status", "confirmed"),
                notes=r.get("notes", ""),
                raw_text=r.get("raw_text", ""),
                confidence=float(r.get("confidence", 1.0)),
            )
            parsed_evidence = self.parse_single_message(
                message_id=cached_evidence.message_id,
                user_id=cached_evidence.user_id,
                message_text=cached_evidence.raw_text,
                request_id=cached_evidence.request_id,
                related_event_id=cached_evidence.related_event_id,
                sent_at=cached_evidence.sent_at,
                source_type=cached_evidence.source_type,
            )
            # Re-parse cached raw text so parser improvements cannot leave stale semantics behind.
            evidence = (
                parsed_evidence
                if parsed_evidence.evidence_type != EvidenceType.GENERAL_NOTIFICATION
                else cached_evidence
            )
            self._index_record(evidence)

    def _index_record(self, evidence: MessageEvidence) -> None:
        self._by_message_id[evidence.message_id] = evidence
        self._by_user_id[evidence.user_id].append(evidence)
        if evidence.related_event_id:
            self._by_event_id[evidence.related_event_id].append(evidence)
        if evidence.request_id:
            self._by_request_id[evidence.request_id].append(evidence)

    @classmethod
    def sanitize_untrusted_text(cls, text: str) -> str:
        """Strip adversarial prompt-injection payloads from untrusted message text."""
        sanitized = text
        for pattern in cls._INJECTION_PATTERNS:
            sanitized = pattern.sub("[INJECTION_ATTEMPT_IGNORED]", sanitized)
        return sanitized

    @classmethod
    def parse_single_message(
        cls,
        message_id: str,
        user_id: str,
        message_text: str,
        request_id: str | None = None,
        related_event_id: str | None = None,
        sent_at: datetime | None = None,
        source_type: str = "sms",
    ) -> MessageEvidence:
        """Deterministically extract structured evidence from raw message text."""
        # Sanitize against prompt injection
        safe_text = cls.sanitize_untrusted_text(message_text)

        # Parse money
        amt: Decimal | None = None
        curr: str | None = None
        money_match = re.search(r"(EUR|USD|IDR|INR|ZAR)\s*([\d,]+(?:\.\d+)?)", safe_text, re.I)
        if money_match:
            curr = money_match.group(1).upper()
            amt = Decimal(money_match.group(2).replace(",", ""))
        else:
            money_match2 = re.search(r"([\d,]+(?:\.\d+)?)\s*(EUR|USD|IDR|INR|ZAR)", safe_text, re.I)
            if money_match2:
                amt = Decimal(money_match2.group(1).replace(",", ""))
                curr = money_match2.group(2).upper()

        # Parse date
        eff_date: date | None = None
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", safe_text)
        if date_m:
            eff_date = date.fromisoformat(date_m.group(1))
        else:
            date_m2 = re.search(
                r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
                safe_text,
                re.I,
            )
            if date_m2:
                month_map = {
                    "january": 1,
                    "february": 2,
                    "march": 3,
                    "april": 4,
                    "may": 5,
                    "june": 6,
                    "july": 7,
                    "august": 8,
                    "september": 9,
                    "october": 10,
                    "november": 11,
                    "december": 12,
                }
                day = int(date_m2.group(1))
                mon = month_map[date_m2.group(2).lower()]
                yr = int(date_m2.group(3))
                eff_date = date(yr, mon, day)

        evidence_type = EvidenceType.GENERAL_NOTIFICATION
        status = "informational"
        notes = ""
        additional_amount: Decimal | None = None

        # Multilingual matching rules (English and Indonesian)
        if re.search(r"rent.*(?:increase|by 12%)|sewa.*naik", safe_text, re.I):
            evidence_type = EvidenceType.RENT_INCREASE
            notes = "Rent increase reported; amount not specified"
            pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", safe_text)
            if pct_m:
                notes = f"Rent increased by {pct_m.group(1)}%"
        elif re.search(r"first salary|gaji pertama", safe_text, re.I):
            evidence_type = EvidenceType.FIRST_SALARY_CONFIRMED
            status = "confirmed"
        elif re.search(
            r"salary of .*confirmed for|gaji sebesar .*dikonfirmasi untuk", safe_text, re.I
        ):
            evidence_type = EvidenceType.FIRST_SALARY_CONFIRMED
            status = "confirmed"
        elif re.search(r"temporary monthly pay|gaji (?:bulanan )?sementara", safe_text, re.I):
            evidence_type = EvidenceType.TEMPORARY_SALARY
            status = "confirmed"
        elif re.search(r"(?:salary|gaji).*(?:increased to|naik menjadi)", safe_text, re.I):
            evidence_type = EvidenceType.SALARY_INCREASE
            status = "confirmed"
        elif re.search(r"reduced to.*unpaid leave|dikurangi menjadi.*cuti", safe_text, re.I):
            evidence_type = EvidenceType.UNPAID_LEAVE_REDUCTION
            status = "confirmed"
        elif re.search(
            r"confirmed salary is now expected on|gaji yang (?:sudah )?dikonfirmasi "
            r"(?:sekarang|kini) diperkirakan(?: masuk)?",
            safe_text,
            re.I,
        ):
            evidence_type = EvidenceType.SALARY_DATE_CHANGE
            status = "confirmed"
        elif re.search(
            r"One household employment.*ended|Salah satu sumber pendapatan.*berakhir",
            safe_text,
            re.I,
        ):
            evidence_type = EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION
            status = "confirmed"
        elif re.search(r"employment has ended|hubungan kerja.*berakhir", safe_text, re.I):
            evidence_type = EvidenceType.CONTRACT_ENDED
            status = "confirmed"
        elif re.search(r"seasonal contract has ended|kontrak musiman.*berakhir", safe_text, re.I):
            evidence_type = EvidenceType.CONTRACT_ENDED
            status = "confirmed"
        elif re.search(
            r"transfer between your (?:two )?accounts|transfer antara (?:kedua akun|dua rekening)",
            safe_text,
            re.I,
        ):
            evidence_type = EvidenceType.INTERNAL_TRANSFER
            status = "neutral"
        elif re.search(r"refund has been initiated|pengembalian dana.*dimulai", safe_text, re.I):
            evidence_type = EvidenceType.PENDING_REFUND
            status = "pending"
        elif re.search(r"portfolio.*(?:market value|nilai pasar)", safe_text, re.I):
            evidence_type = EvidenceType.UNREALIZED_PORTFOLIO
            status = "unrealized"
        elif re.search(r"payout.*pending|pembayaran.*tertunda", safe_text, re.I):
            evidence_type = EvidenceType.PENDING_PAYOUT
            status = "pending"
        elif re.search(
            r"bonus.*(?:pending|review|penilaian)|komisi.*belum disetujui", safe_text, re.I
        ):
            evidence_type = EvidenceType.PENDING_BONUS_OR_COMMISSION
            status = "pending"
        elif re.search(r"prize claim.*processing|klaim hadiah.*diproses", safe_text, re.I):
            evidence_type = EvidenceType.PENDING_PRIZE
            status = "pending"
        elif re.search(r"prize proceeds have reached|hasil hadiah telah masuk", safe_text, re.I):
            evidence_type = EvidenceType.PRIZE_SETTLED
            status = "settled"
        elif re.search(
            r"client approved an invoice|klien menyetujui pembayaran faktur", safe_text, re.I
        ):
            evidence_type = EvidenceType.INVOICE_APPROVED
            status = "confirmed"
        elif re.search(
            r"foreign-currency refund|pengembalian dana.*mata uang asing", safe_text, re.I
        ):
            evidence_type = EvidenceType.FOREIGN_REFUND_PROCESSING
            status = "pending"
        elif re.search(
            r"receipt (?:has|contains) the final|tanda terima memiliki jumlah", safe_text, re.I
        ):
            evidence_type = EvidenceType.PAYMENT_RECEIPT_CONFIRMED
            status = "confirmed"
        elif re.search(
            r"(?:regular|confirmed)?\s*(?:salary|gaji).*(?:resumes|confirmed|dimulai kembali)",
            safe_text,
            re.I,
        ):
            evidence_type = EvidenceType.SALARY_RESUMED
            status = "confirmed"
        elif re.search(
            r"confirmed base salary|gaji pokok.*dikonfirmasi|gaji rutin.*dikonfirmasi",
            safe_text,
            re.I,
        ):
            evidence_type = EvidenceType.SALARY_RESUMED
            status = "confirmed"
        elif re.search(r"arrears adjustment|penyesuaian tunggakan", safe_text, re.I):
            evidence_type = EvidenceType.SALARY_ARREARS_ADJUSTMENT
            status = "confirmed"
            money_mentions = re.findall(
                r"(?:EUR|USD|IDR|INR|ZAR)\s*([\d,]+(?:\.\d+)?)",
                safe_text,
                re.I,
            )
            if len(money_mentions) >= 2:
                additional_amount = Decimal(money_mentions[1].replace(",", ""))

        return MessageEvidence(
            message_id=message_id,
            user_id=user_id,
            request_id=request_id,
            related_event_id=related_event_id,
            sent_at=sent_at,
            source_type=source_type,
            evidence_type=evidence_type,
            amount=amt,
            additional_amount=additional_amount,
            currency=curr,
            effective_date=eff_date,
            status=status,
            notes=notes,
            raw_text=message_text,
            confidence=1.0,
        )

    @property
    def total_messages(self) -> int:
        return len(self._by_message_id)

    def get_by_message_id(self, message_id: str) -> MessageEvidence | None:
        return self._by_message_id.get(message_id)

    def get_for_user(self, user_id: str) -> list[MessageEvidence]:
        return self._by_user_id.get(user_id, [])

    def get_for_event(self, event_id: str) -> list[MessageEvidence]:
        return self._by_event_id.get(event_id, [])

    def get_for_request(self, request_id: str) -> list[MessageEvidence]:
        return self._by_request_id.get(request_id, [])

    def all_records(self) -> list[MessageEvidence]:
        return list(self._by_message_id.values())
