import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse


RESOLUTIONS = "2160 1440 1080"

VIDEO_SORT_FIELDS = [
    "+res",
    "+vbr",
    "+tbr",
    "vext:webm",
    "vext:mp4",
    "vcodec:av01",
    "vcodec:vp9",
    "vcodec:avc1",
]

AUDIO_SORT_FIELDS = [
    "+abr",
    "+asr",
    "aext:webm",
    "aext:m4a",
    "acodec:opus",
    "acodec:aac",
]

COMBINED_SORT_FIELDS = VIDEO_SORT_FIELDS + AUDIO_SORT_FIELDS
COMBINED_ORDER = ",".join(COMBINED_SORT_FIELDS)

YT_DLP_CLI = [
    "yt-dlp",
    "--js-runtimes",
    "node",
    "--format-sort-force",
    "-F",
    "-S",
    COMBINED_ORDER,
]

CONCURRENT_FRAGMENTS = 4

FILENAME_FORBIDDEN = "\\/:*?\"<>|"
FILENAME_TRANSLATION = {ord(ch): None for ch in FILENAME_FORBIDDEN}
for _code in range(0x00, 0x20):
    FILENAME_TRANSLATION[_code] = None
FILENAME_RESERVED = {
    "CON","PRN","AUX","NUL",
    "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
    "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
}
WS_REGEX = re.compile(r"\s+")


# Função responsável por validar dependências externas críticas (Node.js e FFmpeg) antes da execução
def check_requirements():
    missing = []
    if shutil.which("node") is None:
        missing.append("Node.js")
    if shutil.which("ffmpeg") is None:
        missing.append("FFmpeg")
    if missing:
        sep = " e " if len(missing) == 2 else ", "
        print("\nDependências ausentes: " + sep.join(missing) + ".")
        print("Instale as dependências e tente novamente.")
        input("\nPressione Enter para sair...")
        raise SystemExit(1)


# Converte diferentes formas de URL do YouTube para o formato canônico /watch?v=ID
def normalize_youtube_link(link):
    try:
        u = urlparse(link)
    except Exception:
        return None
    host = (u.netloc or "").lower()
    path = u.path or ""
    qs = parse_qs(u.query or "")
    vid = None
    if "youtube.com" in host:
        if path.startswith("/watch"):
            vid = (qs.get("v") or [None])[0]
        elif path.startswith("/shorts/"):
            vid = path.split("/shorts/")[-1].split("/")[0] or None
    elif host == "youtu.be":
        parts = [p for p in path.split("/") if p]
        vid = parts[0] if parts else None
    if not vid:
        return None
    return f"https://www.youtube.com/watch?v={vid}"


# Função que utiliza yt-dlp para obter informações do vídeo em formato JSON
def probe_video_info(link):
    try:
        proc = subprocess.run(["yt-dlp", "--skip-download", "-J", link], capture_output=True, text=True)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "{}")
    except Exception:
        return None


# Função que determina se o vídeo é ao vivo ou não
def is_live_video(link):
    info = probe_video_info(link)
    if not info:
        return False
    live_status = str(info.get("live_status") or "").lower()
    if info.get("is_live") is True:
        return True
    return live_status in {"is_live", "live", "is_upcoming", "upcoming"}


# Função que sanitiza nomes de arquivos removendo caracteres inválidos e termos reservados do Windows
def sanitize_filename(name):
    name = unicodedata.normalize("NFKC", name)
    sanitized = name.translate(FILENAME_TRANSLATION)
    sanitized = WS_REGEX.sub(" ", sanitized)
    sanitized = sanitized.lstrip(" ")
    sanitized = sanitized.lstrip(".")
    sanitized = sanitized.rstrip(" .")
    stem = sanitized
    if stem.upper() in FILENAME_RESERVED:
        stem = ""
    if not stem:
        stem = "untitled"
    return stem


# Função que executa yt-dlp para listar formatos utilizando leitura assíncrona com threads e exibe um spinner
def run_yt_dlp(link):
    cli = YT_DLP_CLI + [link]
    proc = subprocess.run(cli, capture_output=True, text=True)
    return proc.stdout if proc.stdout else proc.stderr


# Função que filtra e mapeia a saída do yt-dlp em vídeos/áudios por resolução desejada
def parse_available(raw, resolutions):
    lines = raw.splitlines()
    pattern = re.compile(r'^\s*\d+')
    res_list = resolutions.split()

    # Seleção das linhas de vídeo que possuem IDs válidos e resoluções alvo
    video_lines = [
        line for line in lines
        if pattern.match(line) and any(res in line for res in res_list) and "video" in line.lower()
    ]

    # Seleção das linhas de áudio contendo apenas faixas de áudio (sem vídeo)
    audio_lines = [
        line for line in lines
        if pattern.match(line) and "audio only" in line.lower()
    ]

    # Cria mapas id->linha para facilitar escolha posterior
    video_map = {line.split()[0]: line for line in video_lines}
    audio_map = {line.split()[0]: line for line in audio_lines}
    return video_map, audio_map


# Função que gera arquivo de referência (info.txt) com as listas de vídeos e áudios disponíveis
def write_selection_info(video_map, audio_map, out_path, title=None):
    content_parts = []
    if title:
        content_parts.append(title + "\n\n")
    content_parts.append("VÍDEOS:\n")
    content_parts.append("\n")
    if video_map:
        for line in video_map.values():
            content_parts.append(line + "\n")
    else:
        content_parts.append("Nenhum vídeo encontrado\n")
    content_parts.append("\n\n")
    content_parts.append("ÁUDIOS:\n")
    content_parts.append("\n")
    if audio_map:
        for line in audio_map.values():
            content_parts.append(line + "\n")
    else:
        content_parts.append("Nenhum áudio encontrado\n")
    new_content = "".join(content_parts)
    try:
        existing = Path(out_path).read_text(encoding="utf-8")
    except Exception:
        existing = None
    if existing != new_content:
        Path(out_path).write_text(new_content, encoding="utf-8")


# Função de prompt que valida o ID inserido garantindo que pertence às opções disponíveis
def prompt_choice(prompt, choices, allow_blank=False):
    choice_set = set(choices)
    while True:
        value = input(prompt).strip()
        if allow_blank and value == "":
            return None
        if value in choice_set:
            return value
        print("ID inválido. Insira um ID listado em \"info.txt\".\n")


# Função principal: orquestra coleta de link, listagem de formatos, seleção e download/merge
def main():
    check_requirements()

    # Loop principal para permitir múltiplos downloads sequenciais ou saída
    while True:
        link = input("\nInsira um link do YouTube: ").strip()
        normalized = normalize_youtube_link(link)
        info = probe_video_info(normalized) if normalized else None
        live = False
        if info:
            live_status = str((info.get("live_status") or "").lower())
            live = info.get("is_live") is True or live_status in {"is_live", "live", "is_upcoming", "upcoming"}
        while not normalized or live:
            print("Link inválido.\n")
            link = input("Insira um link do YouTube: ").strip()
            normalized = normalize_youtube_link(link)
            info = probe_video_info(normalized) if normalized else None
            live = False
            if info:
                live_status = str((info.get("live_status") or "").lower())
                live = info.get("is_live") is True or live_status in {"is_live", "live", "is_upcoming", "upcoming"}
        output_raw = run_yt_dlp(normalized)
        try:
            existing_raw = Path("raw.txt").read_text(encoding="utf-8")
        except Exception:
            existing_raw = None
        if existing_raw != output_raw:
            Path("raw.txt").write_text(output_raw, encoding="utf-8")

        video_map, audio_map = parse_available(output_raw, RESOLUTIONS)
        write_selection_info(video_map, audio_map, "info.txt", (info or {}).get("title"))

        # Condicional crítica: encerra ciclo se nenhum formato elegível foi encontrado
        if not video_map and not audio_map:
            print("Nenhuma informação encontrada. Verifique o link e tente novamente.")
            again = input("\nDeseja inserir outro link? (S/N): ").strip().lower()
            if again not in ("s", "sim"):
                break
            else:
                continue

        # Exibição do título do vídeo com bordas
        print()
        title = (info or {}).get("title")
        if title:
            w = len(title)
            top = "┌" + ("─" * (w + 2)) + "┐"
            mid = "│ " + title + " │"
            bot = "└" + ("─" * (w + 2)) + "┘"
            print(top)
            print(mid)
            print(bot)

        print("\nAbra o arquivo \"info.txt\" e escolha os IDs desejados.\n")

        # Prompt de seleção de IDs de vídeo e áudio, permitindo ignorar um deles se o outro estiver disponível
        video_allow_blank = bool(audio_map)
        audio_allow_blank = bool(video_map)
        while True:
            video_prompt = "ID do Vídeo (Enter para ignorar): " if video_allow_blank else "ID do Vídeo: "
            video_id = prompt_choice(video_prompt, video_map.keys(), allow_blank=video_allow_blank) if video_map else None
            print()
            audio_prompt = "ID do Áudio (Enter para ignorar): " if audio_allow_blank else "ID do Áudio: "
            audio_id = prompt_choice(audio_prompt, audio_map.keys(), allow_blank=audio_allow_blank) if audio_map else None
            if video_id or audio_id:
                break
            print("\nSelecione pelo menos um ID de Vídeo ou de Áudio.\n")
        confirm = input("\nIniciar download? (S/N): ").strip().lower()
        # Controle de fluxo: confirma início do download, caso contrário retorna ao início
        if confirm not in ("s", "sim"):
            print("Download cancelado pelo usuário.")
            again = input("\nDeseja inserir outro link? (S/N): ").strip().lower()
            if again not in ("s", "sim"):
                break
            else:
                continue

        # Composição do código de formato combinando vídeo+áudio
        format_code = (
            video_id
            if video_id and not audio_id
            else f"{video_id}+{audio_id}" if video_id and audio_id else audio_id
        )

        out_dir = Path("videos")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(out_dir / "%(title)s.%(ext)s")
        before_files = {p.resolve() for p in out_dir.glob("*") if p.is_file()}

        download_cli = [
            "yt-dlp",
            "--js-runtimes",
            "node",
            "-q",
            "--no-warnings",
            "--progress",
            "--concurrent-fragments",
            str(CONCURRENT_FRAGMENTS),
            "--add-metadata",
            "--ppa",
            "ffmpeg:-map_metadata 0 -c copy",
            "-f",
            format_code,
            "-o",
            output_template,
            normalized,
        ]

        # Bloco de execução do download/merge via yt-dlp e ffmpeg
        try:
            proc = subprocess.run(download_cli)
            if proc.returncode == 0:
                print("Download e Merge concluídos com sucesso.")
                after_files = [p for p in out_dir.glob("*") if p.is_file() and p.resolve() not in before_files]
                for p in after_files:
                    new_stem = sanitize_filename(p.stem)
                    if new_stem != p.stem:
                        target = p.with_name(new_stem + p.suffix)
                        i = 1
                        candidate = target
                        # Resolve colisões de nomes anexando um contador incremental
                        while candidate.exists():
                            candidate = p.with_name(f"{new_stem} ({i})" + p.suffix)
                            i += 1
                        try:
                            p.rename(candidate)
                        except Exception:
                            pass
            else:
                print("Ocorreu um erro.")
        except Exception:
            print("Ocorreu um erro.")

        again = input("\nDeseja inserir outro link? (S/N): ").strip().lower()
        if again not in ("s", "sim"):
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.\n")
        raise SystemExit(1)
