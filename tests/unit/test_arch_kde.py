"""Check the Arch KDE product recipe without an ARM64 build runner."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import assemble_rootfs


class ArchKdeRecipeTests(unittest.TestCase):
    def test_defaults_are_simplified_chinese_kde(self):
        cfg = json.loads((ROOT / 'config/arch-kde.json').read_text())
        self.assertEqual(cfg['desktop'], 'kde')
        self.assertEqual(cfg['locale']['lang'], 'zh_CN.UTF-8')
        self.assertEqual(cfg['locale']['timezone'], 'Asia/Shanghai')
        self.assertIn('noto-fonts-cjk', cfg['input_method']['packages'])
        self.assertIn('ibus-libpinyin', cfg['input_method']['packages'])
        for package in ('pipewire-audio', 'gst-plugin-pipewire', 'libwacom',
                        'libevdev', 'libgudev', 'base-devel'):
            self.assertIn(package, cfg['packages'])

    def test_plan_accepts_arch_kde_with_localization_packages(self):
        options = assemble_rootfs.parser().parse_args([
            '--distro', 'arch', '--desktop', 'kde', '--plan',
            '--output', str(ROOT / 'build/distros/arch-kde-plan-test'),
            '--base-url', 'https://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz',
            '--base-sha256', '0' * 64,
            '--extra-package', 'noto-fonts-cjk', '--extra-package', 'ibus-libpinyin'])
        result = assemble_rootfs.plan(options)
        self.assertEqual(result['status'], 'HOST_RECIPE_CANDIDATE')
        self.assertEqual(result['desktop'], 'kde')
        self.assertEqual(result['extra_packages'], ['noto-fonts-cjk', 'ibus-libpinyin'])
        self.assertEqual(result['missing_inputs'], [])


if __name__ == '__main__':
    unittest.main()
