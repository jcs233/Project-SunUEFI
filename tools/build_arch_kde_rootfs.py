#!/usr/bin/env python3
"""Build Arch Linux ARM + KDE with Simplified Chinese defaults and the Piano BSP."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

import assemble_rootfs
import build_arch_ffmpeg
import build_arch_package
import build_release_rootfs as release
import stage_arch_piano
from build import arch_mesa
from build_steamos_rootfs import sensor_sources, sensor_recipes

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def download_base(cfg, inputs):
    """Record the rolling bootstrap digest; the root records package versions."""
    archive = inputs / 'ArchLinuxARM-aarch64.tar.gz'
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        with urllib.request.urlopen(cfg['base_url'], timeout=90) as source, partial.open('wb') as target:
            shutil.copyfileobj(source, target)
        partial.replace(archive)
    return release.digest(archive)


def localize(root, cfg):
    """Simplified Chinese locale, timezone, IBus and the reviewed KDE defaults."""
    locale, method = cfg['locale'], cfg['input_method']
    lang = locale['lang']
    locale_gen = root / 'etc/locale.gen'
    lines = locale_gen.read_text().splitlines()
    wanted = {'zh_CN.UTF-8 UTF-8', 'en_US.UTF-8 UTF-8'}
    entries = {line.strip().lstrip('#') for line in lines}
    for entry in wanted - entries:
        lines.append(entry)
    locale_gen.write_text('\n'.join(lines) + '\n')
    (root / 'etc/locale.conf').write_text('LANG=' + lang + '\nLANGUAGE=' + locale['language'] + '\n')
    (root / 'etc/vconsole.conf').write_text('KEYMAP=' + locale['keymap'] + '\n')
    localtime = root / 'etc/localtime'
    localtime.unlink(missing_ok=True)
    localtime.symlink_to('/usr/share/zoneinfo/' + locale['timezone'])
    environment = {'LANG': lang, **method['environment']}
    (root / 'etc/environment').write_text(
        ''.join(key + '=' + value + '\n' for key, value in environment.items()))

    home = root / 'home/piano'
    config = home / '.config'
    config.mkdir(parents=True, exist_ok=True)
    (config / 'plasma-localerc').write_text(
        '[Formats]\nLANG=' + lang + '\n\n[Translations]\nLANGUAGE=' + lang.split('.')[0] + '\n')
    env_dir = config / 'plasma-workspace/env'
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / 'sunuefi-ibus.sh').write_text(
        ''.join('export ' + key + '=' + value + '\n' for key, value in method['environment'].items()))
    overlay = ROOT / 'linux/desktops/kde/config'
    for source in sorted(overlay.iterdir()):
        if source.name == 'kwinoutputconfig.json':
            continue
        shutil.copy2(source, config / source.name)
    shutil.copy2(ROOT / 'linux/desktops/kde/environment.sh', env_dir / 'sunuefi-scale.sh')
    autostart = config / 'autostart'
    autostart.mkdir(parents=True, exist_ok=True)
    (autostart / 'ibus.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=IBus\nExec=' + method['autostart'] + '\n')
    passwd = (root / 'etc/passwd').read_text()
    fields = next(line.split(':') for line in passwd.splitlines() if line.startswith('piano:'))
    run('chown', '-R', fields[2] + ':' + fields[3], config)
    run('chroot', root, '/usr/bin/locale-gen')
    translations = sorted((root / 'usr/share/locale/zh_CN/LC_MESSAGES').glob('plasma*.mo'))
    return {'lang': lang, 'timezone': locale['timezone'], 'keymap': locale['keymap'],
            'input_method': 'ibus', 'packages': method['packages'],
            'kde_translation_files': [path.name for path in translations]}


def build(args):
    output = args.output.resolve()
    if os.geteuid() or not output.is_relative_to(ROOT / 'build/distros'):
        raise ValueError('Use root and an output below build/distros')
    cfg = json.loads((ROOT / 'config/arch-kde.json').read_text())
    policy = json.loads((ROOT / 'config/release.json').read_text())
    kernel = ROOT / 'artifacts/kernels/release'
    source_record = ROOT / 'build/release/source-manifest.json'
    if not (kernel / 'manifest.json').is_file() or not source_record.is_file():
        raise ValueError('Run ./build.sh linux first; the release kernel manifest is missing')
    inputs = ROOT / 'build/arch-kde-inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    base_hash = download_base(cfg, inputs)
    root = output / 'rootfs'
    if output.exists() and not args.resume:
        raise ValueError('Output already exists; use --resume for this build')
    if not output.exists():
        options = assemble_rootfs.parser().parse_args([
            '--distro', 'arch', '--desktop', 'kde', '--execute',
            '--output', str(output), '--base-file', str(inputs / 'ArchLinuxARM-aarch64.tar.gz'),
            '--base-url', cfg['base_url'], '--base-sha256', base_hash,
            *sum((['--extra-package', name] for name in cfg['input_method']['packages']), [])])
        assemble_rootfs.execute(assemble_rootfs.plan(options))
    elif not (output / 'manifest.json').exists():
        raise ValueError('The base desktop assembly did not complete')

    sensors = inputs / 'sensors'
    if not sensors.exists():
        sensor_sources(sensors, policy['sensors'])
    recipes = inputs / 'recipes'
    if not recipes.exists():
        sensor_recipes(recipes, sensors)

    mesa = recipes / 'mesa'
    arch_mesa.recipe(mesa)
    mesa_packages = ROOT / 'build/mesa-pacman/arch-kde'
    if not arch_mesa.is_current(mesa_packages, mesa):
        if mesa_packages.exists():
            shutil.rmtree(mesa_packages)
        build_arch_package.build(root, mesa, mesa_packages, validate=arch_mesa.validate)
        shutil.copy2(mesa / 'SOURCE.json', mesa_packages / 'SOURCE.json')
    else:
        arch_mesa.install_cached(root, mesa_packages)
    ffmpeg = output / 'packages/ffmpeg'
    if not build_arch_ffmpeg.is_current(ffmpeg):
        if ffmpeg.exists():
            shutil.rmtree(ffmpeg)
        build_arch_ffmpeg.build(root, ffmpeg)
    else:
        build_arch_package.install_cached(root, ffmpeg)
    pipewire = output / 'packages/pipewire'
    run(ROOT / 'build.sh', 'pipewire', '--rootfs', root, '--output', pipewire)
    libwacom = output / 'packages/libwacom'
    run(ROOT / 'build.sh', 'libwacom', '--rootfs', root, '--output', libwacom)

    worktree = Path(json.loads(source_record.read_text())['worktree'])
    runtime = output / 'runtime'
    if not (runtime / 'manifest.json').exists():
        run(sys.executable, ROOT / 'tools/build_release_helpers.py',
            '--kernel', kernel, '--source', worktree,
            '--kernel-build', ROOT / 'build/kernels/release',
            '--output', runtime, '--sysroot', args.bootstrap_sysroot.resolve(),
            '--firmware-root', root)
    stage_arch_piano.stage(argparse.Namespace(
        rootfs=root, kernel=kernel, runtime=runtime, sensor_source=sensors,
        bootstrap_sysroot=args.bootstrap_sysroot, desktop='kde', desktop_source=None,
        extensions=ROOT / 'build/nyarch-extensions'))
    # Apply the product localization after the shared overlay so its defaults
    # and the disk-root policy cannot overwrite the Chinese configuration.
    localization = localize(root, cfg)
    (output / 'localization.json').write_text(json.dumps(localization, indent=2) + '\n')
    manifest = output / 'manifest.json'
    record = json.loads(manifest.read_text())
    record.update(base_archive_sha256=base_hash, arch_kde_inputs=cfg,
                  localization=localization,
                  ffmpeg=json.loads((ffmpeg / 'SOURCE.json').read_text()),
                  pipewire=json.loads((pipewire / 'SOURCE.json').read_text()),
                  libwacom=json.loads((libwacom / 'SOURCE.json').read_text()))
    manifest.write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/distros/arch-kde-piano')
    parser.add_argument('--bootstrap-sysroot', type=Path, default=Path('/'))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        raise SystemExit(run('unshare', '--mount', '--propagation', 'private',
                             sys.executable, __file__, *sys.argv[1:], '--worker').returncode)
    build(args)
