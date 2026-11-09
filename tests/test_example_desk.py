"""New v0.4.1 regressions: examples, real session IDs, terminal-only control."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
from blackswarm import app, core
from blackswarm.neon import Neon


class ExampleDeskTests(unittest.TestCase):
    def seed(self, vault):
        return vault.store('ethical hacking cybersecurity','live',500,
                           [{**core.make_record('https://example.org/edu','Public research','', 'Wikipedia'), 'sources':['Wikipedia']}],
                           {'wikipedia':{'status':'ok','found':1}})

    def test_example_desk_separates_examples_from_actual_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            sid=self.seed(vault)
            with patch.object(app,'VAULT',vault), redirect_stdout(io.StringIO()) as out:
                app._terminal_examples(Neon('never'))
            visible=out.getvalue()
            self.assertIn('EXAMPLE DESK',visible)
            self.assertIn('NOT your actual sessions',visible)
            self.assertIn('YOUR ACTUAL SAVED SESSION IDs',visible)
            self.assertIn(f'#{sid}',visible)
            self.assertIn('ethical hacking cybersecurity',visible)
            self.assertIn('type ?',visible)

    def test_menu_eight_help_with_no_browser_and_no_new_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            self.seed(vault)
            with patch.object(app.core,'Vault',return_value=vault), \
                 patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser should not open')), \
                 patch('builtins.input',side_effect=['8','0']), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertEqual(app.main(['--color','never']),0)
            self.assertIn('[8]',out.getvalue())
            self.assertIn('EXAMPLE DESK',out.getvalue())
            self.assertEqual(vault.count_runs(),1)

    def test_id_prompt_lists_actual_ids_and_help_then_returns_id(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            sid=self.seed(vault)
            with patch.object(app,'VAULT',vault), \
                 patch('builtins.input',side_effect=['?','99',str(sid)]), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertEqual(app._ask_session_id(Neon('never')),sid)
            self.assertIn(f'RECENT SESSION IDs: #{sid}',out.getvalue())
            self.assertIn('EXAMPLE DESK',out.getvalue())
            self.assertIn('not in this vault',out.getvalue())
            self.assertEqual(vault.count_runs(),1)

    def test_no_session_and_cancel_without_modifications(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            with patch.object(app,'VAULT',vault), \
                 patch('builtins.input',side_effect=['']), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertIsNone(app._ask_session_id(Neon('never')))
            self.assertIn('No saved sessions yet',out.getvalue())
            self.assertEqual(vault.count_runs(),0)

    def test_examples_flag_read_only_no_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            sid=self.seed(vault)
            with patch.object(app.core,'Vault',return_value=vault), \
                 patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser should not open')), \
                 redirect_stdout(io.StringIO()) as out:
                self.assertEqual(app.main(['--examples','--color','never']),0)
            self.assertIn(f'#{sid}',out.getvalue())
            self.assertEqual(vault.count_runs(),1)

    def test_uses_unchanged_v4_store_path(self):
        self.assertEqual(core.STORE.name,'blackswarm-v4-vault')


if __name__=='__main__':
    unittest.main()
