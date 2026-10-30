"""Local WeChat share exports: preserve provenance, render daily human chats.

No network access, OCR, inference, or diary prose generation. The ZIP is the
authority; receiver receipts only locate it. Quoted chats stay inside the
forwarding message and are never promoted to timeline events.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
import re
import tempfile
from urllib.parse import quote
import zipfile

MESSAGE = re.compile(r"(?m)^·(?P<sender>[^\n]+)\n(?P<stamp>\d{4}[-/]\d{2}[-/]\d{2} +\d{1,2}:\d{2})(?:\r?$)")
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def daily_path(root: Path, target: date, suffix='md') -> Path:
    return root / 'journal' / 'wechat' / target.strftime('%Y/%m') / f'{target.isoformat()}-wechat.{suffix}'


def read_day(root: Path, target: date):
    path = daily_path(root, target, 'json')
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'messages': [], 'exports': {}}


def changed_write(path, text):
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
        output.write(text)
        temporary = output.name
    os.replace(temporary, path)
    return True


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def parse_text(text):
    text = text.replace('\r\n', '\n')
    headers = list(MESSAGE.finditer(text))
    if not headers or text[:headers[0].start()].strip():
        raise ValueError('Unrecognized WeChat text export header')
    messages = []
    for i, header in enumerate(headers):
        stamp = datetime.strptime(header['stamp'].replace('/', '-'), '%Y-%m-%d %H:%M')
        body = text[header.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)].strip('\n')
        messages.append({'sender': header['sender'], 'at': stamp.isoformat(timespec='minutes'), 'body': body})
    return messages


def parse_zip(path: Path, root: Path, *, store_assets=True):
    payload = path.read_bytes()
    export_id = digest(payload)
    assets = {}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        # Never guess which of several text files is the actual transcript.
        candidates = [m for m in members if Path(m.filename).name == 'Chat History.txt']
        if len(candidates) != 1:
            raise ValueError('Expected exactly one Chat History.txt')
        if sum(m.file_size for m in members) > 5 * 1024**3 or len(members) > 20000:
            raise ValueError('Export exceeds receiver size limit')
        raw_text = archive.read(candidates[0])
        messages = parse_text(raw_text.decode('utf-8-sig'))
        basenames = Counter(Path(m.filename).name for m in members if not m.is_dir())
        for member in members:
            if member.is_dir() or member == candidates[0]:
                continue
            name = Path(member.filename).name
            if basenames[name] != 1:
                raise ValueError('Ambiguous attachment filename: ' + name)
            content = archive.read(member)
            sha = digest(content)
            extension = Path(name).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,10}', extension):
                extension = '.bin'
            destination = root / 'journal' / 'wechat' / 'assets' / (sha + extension)
            if store_assets:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if digest(destination.read_bytes()) != sha:
                        raise ValueError('Archived attachment hash mismatch')
                else:
                    with destination.open('xb') as output:
                        output.write(content)
            assets[name] = {'name': name, 'sha256': sha, 'path': destination.relative_to(root).as_posix(),
                            'image': extension in IMAGE_SUFFIXES}
    participants = sorted({m['sender'] for m in messages})
    chat = digest(json_text(participants).encode())[:16]
    occurrences = Counter()
    for message in messages:
        message['attachments'] = [asset for name, asset in assets.items() if name in message['body']]
        identity = json_text([chat, message['sender'], message['at'], message['body'],
                              [a['sha256'] for a in message['attachments']]])
        occurrences[identity] += 1
        message.update(id=digest((identity + str(occurrences[identity])).encode()), chat=chat,
                       participants=participants, occurrence=occurrences[identity])
    return export_id, {'archive': path.relative_to(root).as_posix(), 'sha256': export_id,
                       'text_sha256': digest(raw_text), 'messages': messages,
                       'attachments': list(assets.values())}


def link(path, label):
    return f'[{label}]({quote(path, safe="/")})'


def render_day(root, target, data):
    path = daily_path(root, target)
    relative = lambda p: os.path.relpath(root / p, path.parent)
    lines = ['---', f'date: {target.isoformat()}', 'source: wechat',
             'generated_by: scripts/copilot.py import-wechat', '---', '',
             f'# {target.isoformat()} WeChat', '',
             'Henry 手动选择并通过微信官方共享导出的聊天。以下是原始消息，不是 Copilot 总结。', '',
             '转发内的姓名、时间与图片属于被转发内容，不表示 Henry 在那个时间参与了原聊天。',
             '`[Sticker]` 只有占位时不还原表情包；语音可能被微信完全省略，缺失数量未知。',
             '会话分组按本次导出出现的参与者推导，微信没有提供可靠会话 ID；同名参与者的不同群无法据此区分。', '',
             '## Sources', '']
    for export_id, source in sorted(data['exports'].items()):
        lines += [f'- ZIP `{export_id}`：' + link(relative(source['archive']), '原始导出'),
                  f'  - TXT SHA-256：`{source["text_sha256"]}`']
    lines += ['', '## Messages', '']
    for message in data['messages']:
        lines += [f'### {message["at"].replace("T", " ")} · {message["sender"]}', '',
                  '来源：' + ', '.join('`' + s[:12] + '`' for s in message['sources']), '']
        # Quote every source line: arbitrary Markdown is evidence, never a new
        # top-level diary heading or instruction. Keep nested indentation intact.
        lines += ['> ' + line for line in message['body'].split('\n')]
        for attachment in message['attachments']:
            href = link(relative(attachment['path']), attachment['name'])
            lines += ['', ('!' if attachment['image'] else '') + href]
        if '[Photo]' in message['body'] and not message['attachments']:
            lines += ['', '附件缺失：导出保留了图片标记，但未找到对应文件。']
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def import_exports(root: Path, *, dry_run=False):
    """Merge all receiver ZIPs; never consume, move, or rewrite the originals."""
    root = Path(root).resolve()
    incoming = root / 'journal' / 'wechat-imports'
    if not incoming.exists():
        return {'days': [], 'written': [], 'new_exports': 0, 'warnings': []}
    output = root / 'journal' / 'wechat'
    if dry_run:
        return _import(root, output, incoming, dry_run=True)
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.import.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _import(root, output, incoming, dry_run=False)


def _import(root, output, incoming, *, dry_run):
    catalog_path = output / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {'version': 1, 'exports': {}}
    new_exports = 0
    warnings = []
    for receipt in sorted(incoming.glob('*/receipt.json')):
        try:
            value = json.loads(receipt.read_text(encoding='utf-8'))
            for entry in value['files']:
                archive = (receipt.parent / entry['saved_file']).resolve()
                if not archive.is_relative_to(receipt.parent.resolve()) or not archive.is_file():
                    raise ValueError('Receipt points outside its batch or file is missing')
                actual_hash = digest(archive.read_bytes())
                if actual_hash != entry['sha256']:
                    raise ValueError('ZIP hash differs from receiver receipt')
                if actual_hash in catalog['exports']:
                    continue
                export_id, parsed = parse_zip(archive, root, store_assets=not dry_run)
                catalog['exports'][export_id] = parsed
                new_exports += 1
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
            warnings.append(f'{receipt.relative_to(root)}: {error}')
    by_day = defaultdict(dict)
    sources_by_day = defaultdict(dict)
    # Insertion order retains equal-minute message order in each source.
    for source_id, source in catalog['exports'].items():
        for message in source['messages']:
            day = message['at'][:10]
            if message['id'] not in by_day[day]:
                by_day[day][message['id']] = dict(message, sources=[])
            by_day[day][message['id']]['sources'].append(source_id)
            sources_by_day[day][source_id] = {k: v for k, v in source.items() if k != 'messages'}
    written = []
    for day, messages in sorted(by_day.items()):
        target = date.fromisoformat(day)
        data = {'date': day, 'messages': sorted(messages.values(), key=lambda m: (m['at'], m['chat'])),
                'exports': sources_by_day[day]}
        if not dry_run:
            for path, text in [(daily_path(root, target, 'json'), json_text(data)),
                               (daily_path(root, target), render_day(root, target, data))]:
                if changed_write(path, text):
                    written.append(str(path))
    # Save the catalog last, so an interrupted run can reconstruct projections.
    if not dry_run:
        changed_write(catalog_path, json_text(catalog))
    return {'days': sorted(by_day), 'written': written, 'new_exports': new_exports, 'warnings': warnings}


def journal_index(text, root, target):
    """Add one WeChat source/day link without altering any existing prose."""
    path = daily_path(root, target)
    if not path.exists():
        return text
    marker = '## 💬 From WeChat'
    wikilink = '[[' + path.relative_to(root).with_suffix('').as_posix() + '|微信聊天记录]]'
    bullet = '- ' + wikilink + '：手动选取的原始聊天与附件。'
    if wikilink in text:
        return text
    if marker in text:
        return text.replace(marker, marker + '\n\n' + bullet, 1)
    return text.rstrip() + '\n\n' + marker + '\n\n' + bullet + '\n'
