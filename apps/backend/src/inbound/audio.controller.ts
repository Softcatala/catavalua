import { Controller, Get, Param, Res, Headers } from '@nestjs/common';
import { AudioProxyService } from '../outbound/audio-proxy.service';
import { Response } from 'express';

@Controller('audio')
export class AudioController {
  constructor(private readonly audioProxy: AudioProxyService) {}

  @Get(':clipId')
  async stream(
    @Param('clipId') clipId: string,
    @Headers('range') range: string | undefined,
    @Res() res: Response,
  ) {
    await this.audioProxy.streamAudio(clipId, res, range);
  }
}
