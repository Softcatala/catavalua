import { Controller, Post, Delete, Get, Body, Query, Param, UseGuards } from '@nestjs/common';
import { VoteService } from '../service/vote.service';
import { ApiKeyGuard } from './api-key.guard';
import { IsString, IsNotEmpty, IsNumber, IsOptional, IsIn } from 'class-validator';
import { Type } from 'class-transformer';

class CastVoteDto {
  @IsString() @IsNotEmpty() clipId: string;
  @IsString() @IsNotEmpty() dimension: string;
  @IsOptional() @IsString() targetId?: string;
  @IsString() @IsNotEmpty() username: string;
  @IsNumber() @Type(() => Number) @IsIn([1, -1]) value: number;
}

@Controller('votes')
export class VoteController {
  constructor(private readonly service: VoteService) {}

  @Post()
  async cast(@Body() dto: CastVoteDto) {
    return this.service.cast(dto);
  }

  @UseGuards(ApiKeyGuard)
  @Delete()
  async removeByUser(@Query('username') username: string) {
    if (!username) return { removed: 0 };
    await this.service.removeByUser(username);
    return { ok: true };
  }

  @Get('clip/:clipId')
  async summaryForClip(@Param('clipId') clipId: string) {
    return this.service.summaryForClip(clipId);
  }

  @Get('clip/:clipId/user/:username')
  async userVotes(@Param('clipId') clipId: string, @Param('username') username: string) {
    return this.service.userVotesForClip(clipId, username);
  }

  @Get('stats')
  async stats() {
    return this.service.stats();
  }
}
