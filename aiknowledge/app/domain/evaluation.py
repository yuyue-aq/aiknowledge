from dataclasses import dataclass
import re
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    document_id: UUID
    document_version_id: UUID
    source_block_id: str
    char_start: int
    char_end: int
    text_hash: str
    required: bool = True

    def __post_init__(self):
        if not self.source_block_id or len(self.source_block_id) > 120:
            raise ValueError('证据必须指定有效来源区块。')
        if isinstance(self.char_start, bool) or isinstance(self.char_end, bool) or not isinstance(self.char_start, int) or not isinstance(self.char_end, int):
            raise ValueError('证据区间必须是整数。')
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError('证据区间必须是非空半开区间。')
        if not re.fullmatch(r'[0-9a-f]{64}', self.text_hash):
            raise ValueError('证据 hash 必须是 SHA256。')

    def to_dict(self):
        return {'document_id': str(self.document_id), 'document_version_id': str(self.document_version_id),
            'source_block_id': self.source_block_id, 'char_start': self.char_start, 'char_end': self.char_end,
            'text_hash': self.text_hash, 'required': self.required}

    @classmethod
    def from_dict(cls, value):
        return cls(UUID(str(value['document_id'])), UUID(str(value['document_version_id'])),
            value['source_block_id'], value['char_start'], value['char_end'], value['text_hash'], value.get('required', True))
