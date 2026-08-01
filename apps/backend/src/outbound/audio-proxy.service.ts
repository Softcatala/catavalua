import { Injectable, NotFoundException, ServiceUnavailableException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Clip } from '../domain/clip.entity';
import { Response } from 'express';
import * as https from 'https';
import * as http from 'http';
import { MetricsService } from '../observability/metrics.service';

const HF_BASE =
  'https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main';

@Injectable()
export class AudioProxyService {
  constructor(
    @InjectRepository(Clip) private readonly clips: Repository<Clip>,
    private readonly metrics: MetricsService,
  ) {}

  async streamAudio(clipId: string, res: Response, rangeHeader?: string): Promise<void> {
    const start = process.hrtime.bigint();
    try {
      await this.doStreamAudio(clipId, res, rangeHeader);
      this.metrics.audioProxyRequestsTotal.inc({ outcome: 'ok' });
    } catch (err) {
      this.metrics.audioProxyRequestsTotal.inc({
        outcome: err instanceof NotFoundException ? 'not_found' : 'upstream_error',
      });
      throw err;
    } finally {
      this.metrics.audioProxyDuration.observe(Number(process.hrtime.bigint() - start) / 1e9);
    }
  }

  private async doStreamAudio(clipId: string, res: Response, rangeHeader?: string): Promise<void> {
    const clip = await this.clips.findOne({ where: { clipId } });
    if (!clip) throw new NotFoundException(`Clip ${clipId} not found`);

    if (clip.tarFile == null || clip.tarOffset == null || clip.tarSize == null) {
      throw new NotFoundException(
        `Audio for clip ${clipId} is not indexed yet. Run the indexing script first.`,
      );
    }

    const tarUrl = `${HF_BASE}/audio-${clip.tarFile}.tar`;
    const dataStart = clip.tarOffset;
    const dataEnd = clip.tarOffset + clip.tarSize - 1;

    let fetchStart = dataStart;
    let fetchEnd = dataEnd;
    let statusCode = 200;

    // Support HTTP range requests from browser audio element
    if (rangeHeader) {
      const match = /bytes=(\d+)-(\d*)/.exec(rangeHeader);
      if (match) {
        fetchStart = dataStart + parseInt(match[1], 10);
        fetchEnd = match[2] ? dataStart + parseInt(match[2], 10) : dataEnd;
        fetchEnd = Math.min(fetchEnd, dataEnd);
        statusCode = 206;
      }
    }

    const contentLength = fetchEnd - fetchStart + 1;

    res.setHeader('Content-Type', 'audio/wav');
    res.setHeader('Content-Length', contentLength);
    res.setHeader('Accept-Ranges', 'bytes');
    res.setHeader('Cache-Control', 'public, max-age=3600');
    if (statusCode === 206) {
      res.setHeader(
        'Content-Range',
        `bytes ${fetchStart - dataStart}-${fetchEnd - dataStart}/${clip.tarSize}`,
      );
    }
    res.status(statusCode);

    await new Promise<void>((resolve, reject) => {
      const fetchRange = (targetUrl: string, redirectsLeft = 3) => {
        const url = new URL(targetUrl);
        const protocol = url.protocol === 'https:' ? https : http;

        const req = protocol.get(
          targetUrl,
          { headers: { Range: `bytes=${fetchStart}-${fetchEnd}` } },
          (upstream) => {
            const code = upstream.statusCode ?? 0;
            if (code >= 300 && code < 400 && upstream.headers.location) {
              upstream.resume(); // drain to free socket
              if (redirectsLeft > 0) {
                fetchRange(upstream.headers.location, redirectsLeft - 1);
              } else {
                reject(new ServiceUnavailableException('Too many redirects fetching audio'));
              }
              return;
            }
            if (code >= 400) {
              reject(new ServiceUnavailableException('Failed to fetch audio from upstream'));
              return;
            }
            upstream.pipe(res);
            upstream.on('end', () => {
              this.metrics.audioProxyBytesTotal.inc(contentLength);
              resolve();
            });
            upstream.on('error', reject);
          },
        );
        req.on('error', reject);
      };

      fetchRange(tarUrl);
    });
  }
}
