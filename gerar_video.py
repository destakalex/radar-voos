#!/usr/bin/env python3
"""
Gerador de vídeos "imagem em movimento" (efeito Ken Burns) + narração + legendas.
100% com ferramentas gratuitas:
  - edge-tts   -> narração (vozes Microsoft Edge, gratuito, sem chave)
  - Pexels API -> imagens/vídeos livres de direitos (grátis, precisa de chave grátis)
  - ffmpeg     -> montagem do vídeo, efeito de zoom/pan e legendas

Uso:
    python3 gerar_video.py --topico "Passagens baratas para Lisboa no outono" \
        --idioma pt --voz pt-PT-RaquelNeural --pesquisa "lisbon aerial autumn" \
        --saida video_pt.mp4

Variáveis de ambiente necessárias:
    PEXELS_API_KEY  -> chave grátis em https://www.pexels.com/api/
"""
import argparse
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import requests

PEXELS_URL = "https://api.pexels.com/v1/search"


def buscar_imagens(pesquisa: str, quantidade: int, pasta: Path) -> list[Path]:
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


async def gerar_narracao(texto: str, voz: str, saida_mp3: Path, saida_srt: Path) -> float:
    import edge_tts

    comunicador = edge_tts.Communicate(texto, voz)
    limites = []
    with open(saida_mp3, "wb") as f_audio:
        async for chunk in comunicador.stream():
            if chunk["type"] == "audio":
                f_audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                limites.append(chunk)

    def fmt(t_100ns: int) -> str:
        seg = t_100ns / 10_000_000
        h, resto = divmod(seg, 3600)
        m, s = divmod(resto, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    linhas = []
    grupo = []
    idx = 1
    for limite in limites:
        grupo.append(limite)
        if len(grupo) >= 6:
            inicio = grupo[0]["offset"]
            fim = grupo[-1]["offset"] + grupo[-1]["duration"]
            texto_legenda = " ".join(g["text"] for g in grupo)
            linhas.append(f"{idx}\n{fmt(inicio)} --> {fmt(fim)}\n{texto_legenda}\n")
            idx += 1
            grupo = []
    if grupo:
        inicio = grupo[0]["offset"]
        fim = grupo[-1]["offset"] + grupo[-1]["duration"]
        texto_legenda = " ".join(g["text"] for g in grupo)
        linhas.append(f"{idx}\n{fmt(inicio)} --> {fmt(fim)}\n{texto_legenda}\n")

    saida_srt.write_text("\n".join(linhas), encoding="utf-8")

    duracao = limites[-1]["offset"] / 10_000_000 + limites[-1]["duration"] / 10_000_000 if limites else 0
    return duracao


def montar_video_ken_burns(imagens: list[Path], duracao_total: float, saida_sem_audio: Path):
    n = len(imagens)
    dur_por_imagem = duracao_total / n
    fps = 30
    frames_por_imagem = int(dur_por_imagem * fps)

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
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loop", "1", "-i", str(img),
                    "-vf", f"scale=2200:-1,{zoompan},format=yuv420p",
                    "-t", str(dur_por_imagem), str(clipe),
                ],
                check=True, capture_output=True,
            )
            clipes_tmp.append(clipe)

        lista = tmp / "lista.txt"
        lista.write_text("\n".join(f"file '{c}'" for c in clipes_tmp))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(saida_sem_audio)],
            check=True, capture_output=True,
        )


def juntar_audio_legendas(video_mudo: Path, audio_mp3: Path, srt: Path, saida_final: Path):
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_mudo), "-i", str(audio_mp3),
            "-vf", f"subtitles={srt}:force_style='FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=3'",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(saida_final),
        ],
        check=True, capture_output=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topico", required=True)
    ap.add_argument("--voz", required=True)
    ap.add_argument("--pesquisa", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--n-imagens", type=int, default=6)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("1/4 - a baixar imagens grátis da Pexels...")
        imagens = buscar_imagens(args.pesquisa, args.n_imagens, tmp)

        print("2/4 - a gerar narração + legendas (edge-tts)...")
        mp3 = tmp / "narracao.mp3"
        srt = tmp / "legendas.srt"
        duracao = asyncio.run(gerar_narracao(args.topico, args.voz, mp3, srt))
        print(f"   duração da narração: {duracao:.1f}s")

        print("3/4 - a montar vídeo com efeito Ken Burns...")
        video_mudo = tmp / "mudo.mp4"
        montar_video_ken_burns(imagens, duracao, video_mudo)

        print("4/4 - a juntar áudio + legendas...")
        juntar_audio_legendas(video_mudo, mp3, srt, Path(args.saida))

    print(f"Pronto: {args.saida}")


if __name__ == "__main__":
    main()
