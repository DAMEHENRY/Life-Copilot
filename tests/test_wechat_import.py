"""Synthetic exports only: private chat samples must never enter this repo."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import copilot, wechat_import as wi

DAY = date(2026, 10, 30)


def message(sender, clock, body, day='2026-10-30'):
    return f'·{sender}\n{day} {clock}\n{body}\n\n'


class WeChatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, text, attachments=None):
        self.n += 1
        batch = self.root / 'journal/wechat-imports' / str(self.n)
        batch.mkdir(parents=True)
        path = batch / 'export.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Chat History.txt', text)
            for name, data in (attachments or {}).items():
                archive.writestr('Media/' + name, data)
        receipt = {'files': [{'saved_file': 'export.zip', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
        (batch / 'receipt.json').write_text(json.dumps(receipt))
        return path

    def run_import(self):
        return wi.import_exports(self.root)

    def test_nested_forward_stays_one_message_with_its_image(self):
        quoted = '[Chat History]\n\n    ·Quill\n    2026-10-28 15:42\n    [Photo] nested.jpg'
        self.export(message('Henry', '16:06', quoted) + message('Rowan', '16:07', '[Sticker]'), {'nested.jpg': b'image'})
        self.run_import()
        data = wi.read_day(self.root, DAY)
        self.assertEqual(len(data['messages']), 2)
        self.assertEqual(data['messages'][0]['body'], quoted)
        self.assertEqual(len(data['messages'][0]['attachments']), 1)
        self.assertFalse(wi.daily_path(self.root, date(2026, 10, 28)).exists())
        rendered = wi.daily_path(self.root, DAY).read_text()
        self.assertIn('>     ·Quill', rendered)
        self.assertIn('![nested.jpg]', rendered)
        self.assertIn('> [Sticker]', rendered)

    def test_dates_are_message_dates_and_raw_files_unchanged(self):
        raw = self.export(message('Henry', '23:59', 'yesterday', '2026-10-29') + message('Rowan', '00:01', 'today'))
        before = raw.read_bytes()
        result = self.run_import()
        self.assertEqual(result['days'], ['2026-10-29', '2026-10-30'])
        self.assertEqual(raw.read_bytes(), before)

    def test_noop_rerun_same_zip_and_overlaps_preserve_repeated_messages(self):
        first = message('Henry', '10:00', 'same') * 2 + message('Rowan', '10:01', 'reply')
        original = self.export(first)
        self.run_import()
        self.assertEqual(self.run_import()['written'], [])
        # Byte-identical ZIP in a different receiver batch is not another source.
        other = self.export(first)
        other.write_bytes(original.read_bytes())
        receipt = other.parent / 'receipt.json'
        value = json.loads(receipt.read_text())
        value['files'][0]['sha256'] = hashlib.sha256(other.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(value))
        self.assertEqual(self.run_import()['new_exports'], 0)
        self.export(first + message('Henry', '10:02', 'new'))
        self.run_import()
        self.assertEqual(len(wi.read_day(self.root, DAY)['messages']), 4)
        self.assertEqual(self.run_import()['written'], [])

    def test_missing_image_and_omitted_voice_are_not_invented(self):
        self.export(message('Henry', '10:00', '[Photo] missing.jpg') + message('Rowan', '10:01', '[Sticker]'))
        self.run_import()
        text = wi.daily_path(self.root, DAY).read_text()
        self.assertIn('附件缺失', text)
        self.assertIn('缺失数量未知', text)
        self.assertEqual(list((self.root / 'journal/wechat').glob('assets/*')), [])

    def test_unpadded_export_date_and_markdown_file_remain_attachment(self):
        name = 'reading-notes.md'
        content = '# A document\n\nThis belongs to the attachment, not the chat.\n'
        self.export(message('Rowan', '16:16', 'hello', '2026-7-8')
                    + message('Henry', '16:18', '[File] ' + name, '2026-7-8'),
                    {name: content.encode()})
        self.run_import()
        target = date(2026, 7, 8)
        data = wi.read_day(self.root, target)
        self.assertEqual(len(data['messages']), 2)
        self.assertEqual(data['messages'][0]['at'], '2026-07-08T16:16')
        attachment = data['messages'][1]['attachments'][0]
        self.assertEqual((self.root / attachment['path']).read_text(), content)
        rendered = wi.daily_path(self.root, target).read_text()
        self.assertIn('[reading-notes.md](', rendered)
        self.assertNotIn('![reading-notes.md]', rendered)
        self.assertNotIn('This belongs to the attachment', rendered)

    def test_bad_receipt_and_unknown_format_warn_and_leave_other_sources(self):
        self.export('not an export')
        self.export(message('Henry', '10:00', 'good'))
        result = self.run_import()
        self.assertEqual(len(result['warnings']), 1)
        self.assertEqual(len(wi.read_day(self.root, DAY)['messages']), 1)

    def test_dry_run_writes_nothing_and_source_removal_drops_nothing(self):
        raw = self.export(message('Henry', '10:00', 'hello'))
        result = wi.import_exports(self.root, dry_run=True)
        self.assertEqual(result['new_exports'], 1)
        self.assertFalse((self.root / 'journal/wechat').exists())
        self.run_import()
        raw.rename(raw.with_suffix('.held'))
        result = self.run_import()
        self.assertEqual(len(result['warnings']), 1)
        self.assertEqual(len(wi.read_day(self.root, DAY)['messages']), 1)

    def test_journal_index_adds_once_without_rewriting_any_prose(self):
        self.export(message('Henry', '10:00', 'hello'))
        self.run_import()
        text = '# day\n\nhandwritten text\n\n## What Life Copilot Said\n\nreply\n'
        changed = wi.journal_index(text, self.root, DAY)
        self.assertTrue(changed.startswith(text.rstrip()))
        self.assertEqual(wi.journal_index(changed, self.root, DAY), changed)
        self.assertNotIn('From Kai', changed)

    def test_read_plan_and_timeline_ignore_nested_timestamps(self):
        quote = '[Chat History]\n\n    ·Quill\n    2026-10-30 12:00\n    quoted'
        self.export(message('Henry', '16:06', quote) + message('Rowan', '16:07', 'yes'))
        self.run_import()
        with patch.object(copilot, 'ROOT', self.root), patch.object(copilot, 'JOURNAL_DIR', self.root / 'journal'), \
             patch.object(copilot, 'AI_CONVERSATIONS_DIR', self.root / 'journal/ai-conversations'):
            rendered = copilot.render_day_timeline(DAY)
            self.assertIn('16:06–16:07 · WeChat `Rowan` · Henry 1, others 1', rendered)
            self.assertNotIn('12:00 ·', rendered)
            plan = copilot.format_read_budget(copilot.audit_read_budget(DAY))
            self.assertTrue(any('WeChat source to read in full' in line for line in plan))

    def test_archive_hook_ingests_without_touching_diary_on_daytime_refresh(self):
        self.export(message('Henry', '16:06', 'hello') + message('Rowan', '16:07', 'yes')
                    + message('Henry', '23:59', 'older', '2026-10-29'))
        journal = self.root / 'journal/2026/10/2026-10-30.md'
        journal.parent.mkdir(parents=True)
        journal.write_text('# day\n\n## 💬 From Kai\n')
        yesterday = journal.with_name('2026-10-29.md')
        yesterday.write_text('# yesterday\n\nhandwritten\n')
        patches = [patch.object(copilot, 'ROOT', self.root),
                   patch.object(copilot, 'JOURNAL_DIR', self.root / 'journal'),
                   patch.object(copilot, 'AI_CONVERSATIONS_DIR', self.root / 'journal/ai-conversations'),
                   patch.object(copilot, 'export_codex_day_transcript', return_value=''),
                   patch.object(copilot, 'export_life_claude_renderer_day_transcript', return_value=('', 0, 0)),
                   patch.object(copilot, 'export_claude_code_day_transcript', return_value=('', 0, 0)),
                   patch.object(copilot, 'export_openclaw_day_transcript', return_value=('', 0, 0))]
        for p in patches:
            p.start()
        try:
            before = journal.read_bytes()
            with redirect_stdout(io.StringIO()):
                copilot.writeback_ai_day(DAY, update_journal=False)
            self.assertEqual(journal.read_bytes(), before)
            self.assertEqual(yesterday.read_text(), '# yesterday\n\nhandwritten\n')
            with redirect_stdout(io.StringIO()):
                copilot.writeback_ai_day(DAY)
            self.assertIn('From WeChat', journal.read_text())
            self.assertTrue(yesterday.read_text().startswith('# yesterday\n\nhandwritten\n'))
            self.assertIn('From WeChat', yesterday.read_text())
            self.assertNotIn('wechat', journal.read_text().split('From Kai')[1].split('##')[0].lower())
        finally:
            for p in reversed(patches):
                p.stop()


if __name__ == '__main__':
    unittest.main()
