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


# Função que normaliza links do YouTube para formato padrão
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
    forbidden = "\\/:*?\"<>|"
    table = {ord(ch): None for ch in forbidden}
    for code in range(0x00, 0x20):
        table[code] = None
    sanitized = name.translate(table)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.lstrip(" ")
    sanitized = sanitized.lstrip(".")
    sanitized = sanitized.rstrip(" .")
    reserved = {
        "CON","PRN","AUX","NUL",
        "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
        "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
    }
    stem = sanitized
    if stem.upper() in reserved:
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
def write_selection_info(video_map, audio_map, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("VÍDEOS:\n")
        f.write("\n")
        if video_map:
            for line in video_map.values():
                f.write(line + "\n")
        else:
            f.write("Nenhum vídeo encontrado\n")
        f.write("\n\n")
        f.write("ÁUDIOS:\n")
        f.write("\n")
        if audio_map:
            for line in audio_map.values():
                f.write(line + "\n")
        else:
            f.write("Nenhum áudio encontrado\n")


# Função de prompt que valida o ID inserido garantindo que pertence às opções disponíveis
def prompt_choice(prompt, choices, allow_blank=False):
    while True:
        value = input(prompt).strip()
        if allow_blank and value == "":
            return None
        if value in choices:
            return value
        print("ID inválido. Insira um ID listado em \"info.txt\".\n")


# Função principal: orquestra coleta de link, listagem de formatos, seleção e download/merge
def main():
    check_requirements()

    # Loop principal para permitir múltiplos downloads sequenciais ou saída
    while True:
        link = input("\nInsira um link do YouTube: ").strip()
        normalized = normalize_youtube_link(link)
        while not normalized or is_live_video(normalized):
            print("Link inválido.\n")
            link = input("Insira um link do YouTube: ").strip()
            normalized = normalize_youtube_link(link)

        output_raw = run_yt_dlp(normalized)
        Path("raw.txt").write_text(output_raw, encoding="utf-8")

        video_map, audio_map = parse_available(output_raw, RESOLUTIONS)
        write_selection_info(video_map, audio_map, "info.txt")

        # Condicional crítica: encerra ciclo se nenhum formato elegível foi encontrado
        if not video_map and not audio_map:
            print("Nenhuma informação encontrada. Verifique o link e tente novamente.")
            again = input("\nDeseja inserir outro link? (S/N): ").strip().lower()
            if again not in ("s", "sim"):
                break
            else:
                continue

        print("\nAbra o arquivo \"info.txt\" e escolha os IDs desejados.\n")

        # Seleção opcional de ID de vídeo; permite ignorar para baixar apenas áudio
        video_id = prompt_choice("ID do Vídeo (Enter para ignorar): ", video_map.keys(), allow_blank=True) if video_map else None
        print()
        audio_id = prompt_choice("ID do Áudio: ", audio_map.keys()) if audio_map else None
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
            "-f",
            format_code,
            "-o",
            output_template,
            normalized,
        ]

        # Bloco de execução do download/merge via yt-dlp e ffmpeg
        try:
            proc = subprocess.Popen(download_cli, stdout=None, stderr=None)
            proc.wait()
            # Verifica sucesso do processo e aplica sanitização de nomes nos arquivos resultantes
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
