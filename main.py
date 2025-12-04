import itertools
import re
import shutil
import subprocess
import threading
import time

from pathlib import Path


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


# Executa o yt-dlp para listar formatos disponíveis, com leitura assíncrona e spinner
def run_yt_dlp(link):
    cli = YT_DLP_CLI + [link]
    proc = subprocess.Popen(cli, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    spinner = itertools.cycle(["|", "/", "-", "\\"]) 
    stdout_lines = []
    stderr_lines = []
    spinner_stop = threading.Event()

    # Lê linhas de um stream continuamente e acumula em memória
    def _reader(stream, collector):
        for line in iter(stream.readline, ""):
            collector.append(line)
        stream.close()

    # Exibe um spinner até que o evento de parada seja sinalizado
    def _spinner(stop_event):
        while not stop_event.is_set():
            print(f"\rAguarde... {next(spinner)}", end="", flush=True)
            time.sleep(0.10)
        print("\r" + " " * 80 + "\r", end="", flush=True)

    t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_lines), daemon=True)
    t_spin = threading.Thread(target=_spinner, args=(spinner_stop,), daemon=True)
    t_out.start()
    t_err.start()
    t_spin.start()
    t_out.join()
    t_err.join()
    proc.wait()
    spinner_stop.set()
    t_spin.join()
    print("\r", end="")
    return "".join(stdout_lines) if stdout_lines else "".join(stderr_lines)


# Filtra e mapeia linhas de saída para vídeos e áudios disponíveis por resolução
def parse_available(raw, resolutions):
    lines = raw.splitlines()
    pattern = re.compile(r'^\s*\d+')
    res_list = resolutions.split()
    # Seleciona linhas de vídeo que possuem IDs e resoluções desejadas
    video_lines = [
        line for line in lines
        if pattern.match(line) and any(res in line for res in res_list) and "video" in line.lower()
    ]
    # Seleciona linhas de áudio que possuem apenas áudio (sem vídeo)
    audio_lines = [
        line for line in lines
        if pattern.match(line) and "audio only" in line.lower()
    ]
    # Cria mapas id->linha para facilitar escolha posterior
    video_map = {line.split()[0]: line for line in video_lines}
    audio_map = {line.split()[0]: line for line in audio_lines}
    return video_map, audio_map


# Gera arquivo de referência com listas de vídeos e áudios para o usuário
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


# Loop de validação que garante que o ID escolhido esteja entre as opções
def prompt_choice(prompt, choices, allow_blank=False):
    while True:
        value = input(prompt).strip()
        if allow_blank and value == "":
            return None
        if value in choices:
            return value
        print("ID inválido. Insira um ID listado em \"info.txt\".\n")


# Verifica dependências externas críticas (Node.js e FFmpeg) antes da execução
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


# Fluxo principal: coleta link, lista formatos, permite seleção e realiza download/merge
def main():
    check_requirements()

    link = input("\nInsira um link do YouTube: ").strip()
    # Valida o link e força novo input até atender os domínios suportados
    while not link or ("youtube.com" not in link and "youtu.be" not in link):
        print("Link inválido.\n")
        link = input("Insira um link do YouTube: ").strip()

    output_raw = run_yt_dlp(link)
    Path("raw.txt").write_text(output_raw, encoding="utf-8")

    video_map, audio_map = parse_available(output_raw, RESOLUTIONS)
    write_selection_info(video_map, audio_map, "info.txt")

    # Interrompe se nenhum formato elegível foi encontrado
    if not video_map and not audio_map:
        print("Nenhuma informação encontrada. Verifique o link e tente novamente.")
        input("Pressione Enter para sair...")
        raise SystemExit

    print("\nAbra o arquivo \"info.txt\" e escolha os IDs desejados.\n")

    video_id = prompt_choice("ID do Vídeo (Enter para ignorar): ", video_map.keys(), allow_blank=True) if video_map else None
    print()
    audio_id = prompt_choice("ID do Áudio: ", audio_map.keys()) if audio_map else None
    confirm = input("\nIniciar download? (S/N): ").strip().lower()
    # Prossegue apenas com confirmação explícita do usuário
    if confirm not in ("s", "sim"):
        print("Download cancelado pelo usuário.\n")
        input("Pressione Enter para sair...")
        raise SystemExit

    # Monta o código de formato combinando vídeo+áudio quando necessário
    format_code = (
        video_id
        if video_id and not audio_id
        else f"{video_id}+{audio_id}" if video_id and audio_id else audio_id
    )

    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "%(title)s.%(ext)s")

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
        link,
    ]

    try:
        print("Aguarde...")
        # Executa o download e merge via yt-dlp/ffmpeg de forma silenciosa
        proc = subprocess.Popen(download_cli, stdout=None, stderr=None)
        proc.wait()
        if proc.returncode == 0:
            print("Download e Merge concluídos com sucesso.")
        else:
            print("Ocorreu um erro.")
    except Exception:
        print("Ocorreu um erro.")
    input("Pressione Enter para sair...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.\n")
        raise SystemExit(1)
