#!/usr/bin/env python3
"""
Gerador de vídeos "imagem em movimento" (efeito Ken Burns) + narração + legendas.
100% com ferramentas gratuitas:
  - Piper TTS  -> narração neural, 100% local/offline (só precisa de rede
                  para baixar o modelo de voz uma vez; a síntese em si não
                  depende de nenhum serviço externo)
  - Pexels API -> imagens livres de direitos (grátis, precisa de chave grátis)
  - ffmpeg     -> montagem do vídeo, efeito de zoom/pan e legendas

Nota histórica: a primeira versão deste script usava edge-tts (vozes da
Microsoft Edge). Esse serviço não é oficial/documentado e, na prática,
bloqueia ou fecha silenciosamente as ligações vindas de IPs de datacenter
como os do GitHub Actions (que corre em Azure) — por isso o script passou
a usar o Piper, que corre localmente e não depende de nenhum serviço de
terceiros durante a síntese (só a descarga do modelo de voz precisa de
rede, uma única vez, a partir do Hugging Face).

Uso:
    python3 gerar_video.py --topico "Passagens baratas para Lisboa no outono" \
        --voz pt_PT-tugão-medium --pesquisa "lisbon aerial autumn" \
        --saida video_pt.mp4

Variáveis de ambiente necessárias:
    PEXELS_API_KEY  -> chave grátis em https://www.pexels.com/api/
"""
import argparse
import os
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from urllib.parse import quote

import requests

PEXELS_URL = "https://api.pexels.com/v1/search"

VOICE_PATTERN = re.compile(
    r"^(?P<lang_family>[^_]+)_(?P<lang_region>[^-]+)-(?P<voice_name>[^-]+)-(?P<voice_quality>.+)$"
)
HF_VOICE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "{lang_family}/{lang_code}/{voice_name_q}/{voice_quality}/"
    "{lang_code}-{voice_name_q}-{voice_quality}{extension}?download=true"
)


def buscar_imagens(pesquisa: str, quantidade: int, pasta: Path) -> list[Path]:
    """Baixa `quantidade` imagens grátis da Pexels para a pasta indicada."""
    chave = os.environ.get("PEXELS_API_KEY")
    if not chave:
        raise RuntimeError("Falta a variável de ambiente PEXELS_API_KEY (chave grátis da Pexels).")

    resp = requests.get(
        PEXELS_URL,
        headers={"Authorization": chave},
        params={"query": pesquisa, "per_page": quantidade, "orientation": "landscape"},
        timeout=30,
    )
    resp.raise_for_status()
    fotos = resp.json().get("photos", [])
    if not fotos:
        raise RuntimeError(f"Nenhuma imagem encontrada na Pexels para '{pesquisa}'.")

    caminhos = []
    for i, foto in enumerate(fotos):
        url = foto["src"]["original"]
        destino = pasta / f"img_{i:02d}.jpg"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        destino.write_bytes(r.content)
        caminhos.append(destino)
    return caminhos


def baixar_voz_piper(voz: str, pasta_vozes: Path, tentativas: int = 3) -> Path:
    """Baixa (e põe em cache) os ficheiros .onnx + .onnx.json de uma voz do
    Piper a partir do Hugging Face. Faz o próprio URL-encoding do nome da
    voz (necessário para vozes com acentos, ex: 'pt_PT-tugão-medium')."""
    pasta_vozes.mkdir(parents=True, exist_ok=True)
    modelo = pasta_vozes / f"{voz}.onnx"
    config = pasta_vozes / f"{voz}.onnx.json"

    if modelo.exists() and config.exists() and modelo.stat().st_size > 0:
        return modelo

    m = VOICE_PATTERN.match(voz)
    if not m:
        raise ValueError(
            f"Voz Piper inválida: '{voz}' (esperado <lang>_<REGIAO>-<nome>-<qualidade>, "
            f"ex: en_US-lessac-medium)"
        )
    lang_family = m.group("lang_family")
    lang_region = m.group("lang_region")
    voice_name_q = quote(m.group("voice_name"), safe="")
    voice_quality = m.group("voice_quality")
    lang_code = f"{lang_family}_{lang_region}"

    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            for extension, destino in ((".onnx", modelo), (".onnx.json", config)):
                url = HF_VOICE_URL.format(
                    lang_family=lang_family,
                    lang_code=lang_code,
                    voice_name_q=voice_name_q,
                    voice_quality=voice_quality,
                    extension=extension,
                )
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                destino.write_bytes(r.content)

            if modelo.exists() and modelo.stat().st_size > 0:
                return modelo
        except Exception as e:
            ultimo_erro = e

        print(f"   aviso: tentativa {tentativa}/{tentativas} a baixar a voz '{voz}' falhou, a repetir em 5s...")
        time.sleep(5)

    raise RuntimeError(f"Não foi possível baixar a voz Piper '{voz}'") from ultimo_erro


def gerar_narracao(texto: str, voz: str, pasta_vozes: Path, saida_wav: Path, saida_srt: Path) -> float:
    """Gera a narração com o Piper TTS (100% local) e um ficheiro .srt com
    legendas. O Piper não devolve timestamps por palavra como o edge-tts
    devolvia, por isso as legendas são distribuídas proporcionalmente ao
    número de palavras de cada grupo em relação à duração total do áudio
    (aproximação suficiente para legendas automáticas)."""
    modelo = baixar_voz_piper(voz, pasta_vozes)

    resultado = subprocess.run(
        ["python3", "-m", "piper", "-m", str(modelo), "-f", str(saida_wav), "--", texto],
        capture_output=True,
    )
    if resultado.returncode != 0 or not saida_wav.exists() or saida_wav.stat().st_size == 0:
        raise RuntimeError(
            f"Piper falhou a gerar a narração: {resultado.stderr.decode(errors='replace')[-2000:]}"
        )

    with wave.open(str(saida_wav), "rb") as wf:
        duracao = wf.getnframes() / float(wf.getframerate())

    if duracao <= 0:
        raise RuntimeError("Duração da narração gerada pelo Piper é 0 — abortar antes de gerar vídeo inválido.")

    def fmt(seg: float) -> str:
        h, resto = divmod(seg, 3600)
        m, s = divmod(resto, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    palavras = texto.split()
    total_palavras = max(1, len(palavras))
    tamanho_grupo = 6
    grupos = [palavras[i:i + tamanho_grupo] for i in range(0, len(palavras), tamanho_grupo)]

    linhas = []
    t = 0.0
    for idx, grupo in enumerate(grupos, start=1):
        dur = duracao * (len(grupo) / total_palavras)
        inicio, fim = t, t + dur
        linhas.append(f"{idx}\n{fmt(inicio)} --> {fmt(fim)}\n{' '.join(grupo)}\n")
        t = fim

    saida_srt.write_text("\n".join(linhas), encoding="utf-8")
    return duracao


def montar_video_ken_burns(imagens: list[Path], duracao_total: float, saida_sem_audio: Path):
    """Cria um slideshow com efeito de zoom/pan (Ken Burns) usando ffmpeg,
    com duração total igual à da narração."""
    n = len(imagens)
    dur_por_imagem = duracao_total / n
    fps = 30
    frames_por_imagem = max(1, int(dur_por_imagem * fps))

    clipes_tmp = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for i, img in enumerate(imagens):
            clipe = tmp / f"clip_{i:02d}.mp4"
            zoom_dir = "in" if i % 2 == 0 else "out"
            if zoom_dir == "in":
                zoompan = f"zoompan=z='min(zoom+0.0015,1.3)':d={frames_por_imagem}:s=1920x1080:fps={fps}"
            else:
                zoompan = f"zoompan=z='if(eq(on,0),1.3,max(zoom-0.0015,1.0))':d={frames_por_imagem}:s=1920x1080:fps={fps}"
            resultado = subprocess.run(
                [
                    "ffmpeg", "-y", "-loop", "1", "-i", str(img),
                    "-vf", f"scale=2200:-1,{zoompan},format=yuv420p",
                    "-t", str(max(dur_por_imagem, 1 / fps)), str(clipe),
                ],
                capture_output=True,
            )
            if resultado.returncode != 0 or not clipe.exists() or clipe.stat().st_size == 0:
                raise RuntimeError(
                    f"ffmpeg falhou a criar o clip {i} a partir de {img}: "
                    f"{resultado.stderr.decode(errors='replace')[-2000:]}"
                )
            clipes_tmp.append(clipe)

        lista = tmp / "lista.txt"
        lista.write_text("\n".join(f"file '{c}'" for c in clipes_tmp))
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(saida_sem_audio)],
            capture_output=True,
        )
        if resultado.returncode != 0:
            raise RuntimeError(f"ffmpeg falhou a concatenar os clips: {resultado.stderr.decode(errors='replace')[-2000:]}")


def juntar_audio_legendas(video_mudo: Path, audio_path: Path, srt: Path, saida_final: Path):
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_mudo), "-i", str(audio_path),
            "-vf", f"subtitles={srt}:force_style='FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=3'",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(saida_final),
        ],
        check=True, capture_output=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topico", required=True, help="Texto da narração")
    ap.add_argument("--voz", required=True, help="ID da voz Piper, ex: pt_PT-tugão-medium")
    ap.add_argument("--pesquisa", required=True, help="Termo de pesquisa de imagens na Pexels")
    ap.add_argument("--saida", required=True, help="Ficheiro .mp4 de saída")
    ap.add_argument("--n-imagens", type=int, default=6)
    args = ap.parse_args()

    pasta_vozes = Path.cwd() / "piper_voices"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("1/4 - a baixar imagens grátis da Pexels...")
        imagens = buscar_imagens(args.pesquisa, args.n_imagens, tmp)

        print("2/4 - a gerar narração + legendas (Piper TTS, local)...")
        wav = tmp / "narracao.wav"
        srt = tmp / "legendas.srt"
        duracao = gerar_narracao(args.topico, args.voz, pasta_vozes, wav, srt)
        print(f"   duração da narração: {duracao:.1f}s")

        print("3/4 - a montar vídeo com efeito Ken Burns...")
        video_mudo = tmp / "mudo.mp4"
        montar_video_ken_burns(imagens, duracao, video_mudo)

        print("4/4 - a juntar áudio + legendas...")
        juntar_audio_legendas(video_mudo, wav, srt, Path(args.saida))

    print(f"Pronto: {args.saida}")


if __name__ == "__main__":
    main()
