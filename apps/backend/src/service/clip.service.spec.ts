import { Test } from '@nestjs/testing';
import { TypeOrmModule, getRepositoryToken } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { ClipService } from './clip.service';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';
import { Vote } from '../domain/vote.entity';
import { IssueReport } from '../domain/issue-report.entity';
import { MetricsService } from '../observability/metrics.service';

describe('ClipService', () => {
  let service: ClipService;
  let clips: Repository<Clip>;
  let votes: Repository<Vote>;
  let transcriptions: Repository<Transcription>;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      imports: [
        TypeOrmModule.forRoot({
          type: 'sqlite',
          database: ':memory:',
          entities: [Clip, Transcription, Vote, IssueReport],
          synchronize: true,
        }),
        TypeOrmModule.forFeature([Clip, Transcription, Vote, IssueReport]),
      ],
      providers: [ClipService, MetricsService],
    }).compile();

    service = module.get(ClipService);
    clips = module.get(getRepositoryToken(Clip));
    votes = module.get(getRepositoryToken(Vote));
    transcriptions = module.get(getRepositoryToken(Transcription));
  });

  describe('nextForEvaluation dialect priority', () => {
    it('prefers a clip with a dialect signal (detectedDialect or an existing vote) over one with none', async () => {
      await clips.save(clips.create({ clipId: 'no-signal', tarFile: 1, tarOffset: 0, tarSize: 100 }));
      await clips.save(
        clips.create({ clipId: 'has-detected-dialect', tarFile: 1, tarOffset: 0, tarSize: 100, detectedDialect: 'central' }),
      );

      // Only one candidate has a signal, so it must be the one returned —
      // no need to rely on randomness/repetition to prove the ordering.
      const picked = await service.nextForEvaluation('alice', 'dialect', ['no-signal']);
      expect(picked?.clipId).toBe('has-detected-dialect');
    });

    it('also treats an existing dialect vote (e.g. from scripts/infer_dialect.py) as a signal', async () => {
      await clips.save(clips.create({ clipId: 'no-signal', tarFile: 1, tarOffset: 0, tarSize: 100 }));
      await clips.save(clips.create({ clipId: 'bot-voted', tarFile: 1, tarOffset: 0, tarSize: 100 }));
      await votes.save(votes.create({
        clipId: 'bot-voted',
        dimension: 'dialect',
        targetId: 'valencian',
        username: 'derivat-de-poblacio',
        value: 1,
        createdAt: new Date().toISOString(),
      }));

      const picked = await service.nextForEvaluation('alice', 'dialect', ['no-signal']);
      expect(picked?.clipId).toBe('bot-voted');
    });

    it('falls back to a no-signal clip once every signalled clip is excluded', async () => {
      await clips.save(clips.create({ clipId: 'no-signal', tarFile: 1, tarOffset: 0, tarSize: 100 }));
      await clips.save(
        clips.create({ clipId: 'has-detected-dialect', tarFile: 1, tarOffset: 0, tarSize: 100, detectedDialect: 'central' }),
      );

      const picked = await service.nextForEvaluation('alice', 'dialect', ['has-detected-dialect']);
      expect(picked?.clipId).toBe('no-signal');
    });
  });

  describe('nextForEvaluation audio-indexed requirement', () => {
    it('never returns a transcription-dimension clip without indexed audio', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed', tarFile: 1, tarOffset: 0, tarSize: 100 }));

      const picked = await service.nextForEvaluation('alice', 'transcription', []);
      expect(picked?.clipId).toBe('indexed');
    });

    it('never returns a gender-dimension clip without indexed audio', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed', gender: 'female' }));
      await clips.save(clips.create({ clipId: 'indexed', tarFile: 1, tarOffset: 0, tarSize: 100, gender: 'male' }));

      const picked = await service.nextForEvaluation('alice', 'gender', []);
      expect(picked?.clipId).toBe('indexed');
    });

    it('cycles back to an indexed clip rather than surfacing an unindexed one once every indexed clip is excluded', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed', tarFile: 1, tarOffset: 0, tarSize: 100 }));

      const picked = await service.nextForEvaluation('alice', 'gender', ['indexed']);
      expect(picked?.clipId).toBe('indexed');
    });
  });

  describe('flagIrrelevant', () => {
    it('records the chosen reason as the vote targetId', async () => {
      await clips.save(clips.create({ clipId: 'clip-1' }));

      await service.flagIrrelevant('clip-1', 'alice', 'multiple_speakers');

      const vote = await votes.findOne({ where: { clipId: 'clip-1', dimension: 'relevance', username: 'alice' } });
      expect(vote?.targetId).toBe('multiple_speakers');
      expect(vote?.value).toBe(-1);
    });

    it('updates the same vote in place when the same user re-flags with a different reason, instead of adding a second row', async () => {
      await clips.save(clips.create({ clipId: 'clip-1' }));

      await service.flagIrrelevant('clip-1', 'alice', 'not_catalan');
      await service.flagIrrelevant('clip-1', 'alice', 'code_switching');

      const aliceVotes = await votes.find({ where: { clipId: 'clip-1', dimension: 'relevance', username: 'alice' } });
      expect(aliceVotes).toHaveLength(1);
      expect(aliceVotes[0].targetId).toBe('code_switching');
    });

    it('does not mark the clip irrelevant on a single flag', async () => {
      await clips.save(clips.create({ clipId: 'clip-1' }));

      await service.flagIrrelevant('clip-1', 'alice', 'no_speech');

      // is_relevant is a raw 'integer' column (no boolean transformer), so
      // SQLite hands back 0/1 rather than false/true — 0 is the "marked
      // irrelevant" state, null is "untouched".
      const clip = await clips.findOne({ where: { clipId: 'clip-1' } });
      expect(clip?.isRelevant).not.toBe(0);
    });

    it('marks the clip irrelevant once 2 distinct users flag it, even with different reasons', async () => {
      await clips.save(clips.create({ clipId: 'clip-1' }));

      await service.flagIrrelevant('clip-1', 'alice', 'not_catalan');
      await service.flagIrrelevant('clip-1', 'bob', 'unintelligible');

      const clip = await clips.findOne({ where: { clipId: 'clip-1' } });
      expect(clip?.isRelevant).toBe(0);
    });

    it('re-flagging by the same user alone never trips the 2-flag threshold', async () => {
      await clips.save(clips.create({ clipId: 'clip-1' }));

      await service.flagIrrelevant('clip-1', 'alice', 'not_catalan');
      await service.flagIrrelevant('clip-1', 'alice', 'code_switching');

      const clip = await clips.findOne({ where: { clipId: 'clip-1' } });
      expect(clip?.isRelevant).not.toBe(0);
    });
  });
});
