import { Test } from '@nestjs/testing';
import { TypeOrmModule, getRepositoryToken } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { ClipService } from './clip.service';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';
import { Vote } from '../domain/vote.entity';

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
          entities: [Clip, Transcription, Vote],
          synchronize: true,
        }),
        TypeOrmModule.forFeature([Clip, Transcription, Vote]),
      ],
      providers: [ClipService],
    }).compile();

    service = module.get(ClipService);
    clips = module.get(getRepositoryToken(Clip));
    votes = module.get(getRepositoryToken(Vote));
    transcriptions = module.get(getRepositoryToken(Transcription));
  });

  describe('nextForEvaluation dialect priority', () => {
    it('prefers a clip with a dialect signal (detectedDialect or an existing vote) over one with none', async () => {
      await clips.save(clips.create({ clipId: 'no-signal' }));
      await clips.save(clips.create({ clipId: 'has-detected-dialect', detectedDialect: 'central' }));

      // Only one candidate has a signal, so it must be the one returned —
      // no need to rely on randomness/repetition to prove the ordering.
      const picked = await service.nextForEvaluation('alice', 'dialect', ['no-signal']);
      expect(picked?.clipId).toBe('has-detected-dialect');
    });

    it('also treats an existing dialect vote (e.g. from scripts/infer_dialect.py) as a signal', async () => {
      await clips.save(clips.create({ clipId: 'no-signal' }));
      await clips.save(clips.create({ clipId: 'bot-voted' }));
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
      await clips.save(clips.create({ clipId: 'no-signal' }));
      await clips.save(clips.create({ clipId: 'has-detected-dialect', detectedDialect: 'central' }));

      const picked = await service.nextForEvaluation('alice', 'dialect', ['has-detected-dialect']);
      expect(picked?.clipId).toBe('no-signal');
    });
  });

  describe('nextForEvaluation transcription priority', () => {
    it('prefers a clip with indexed audio AND 2+ model agreement over an unindexed one', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed-and-agreed', tarFile: 1, tarOffset: 0, tarSize: 100 }));
      await transcriptions.save(transcriptions.create({ clipId: 'indexed-and-agreed', origin: 'gemini-a', text: 'hola' }));
      await transcriptions.save(transcriptions.create({ clipId: 'indexed-and-agreed', origin: 'gemini-b', text: 'hola' }));

      const picked = await service.nextForEvaluation('alice', 'transcription', ['not-indexed']);
      expect(picked?.clipId).toBe('indexed-and-agreed');
    });

    it('prefers an indexed clip without agreement over an unindexed one when no agreed+indexed clip exists', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed-only', tarFile: 1, tarOffset: 0, tarSize: 100 }));

      const picked = await service.nextForEvaluation('alice', 'transcription', []);
      expect(picked?.clipId).toBe('indexed-only');
    });

    it('falls back to an unindexed clip once every indexed clip is excluded', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed-only', tarFile: 1, tarOffset: 0, tarSize: 100 }));

      const picked = await service.nextForEvaluation('alice', 'transcription', ['indexed-only']);
      expect(picked?.clipId).toBe('not-indexed');
    });
  });

  describe('nextForEvaluation gender priority', () => {
    it('prefers a clip with indexed audio over one without', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed', gender: 'female' }));
      await clips.save(clips.create({ clipId: 'indexed', tarFile: 1, tarOffset: 0, tarSize: 100, gender: 'male' }));

      const picked = await service.nextForEvaluation('alice', 'gender', []);
      expect(picked?.clipId).toBe('indexed');
    });

    it('falls back to an unindexed clip once every indexed clip is excluded', async () => {
      await clips.save(clips.create({ clipId: 'not-indexed' }));
      await clips.save(clips.create({ clipId: 'indexed', tarFile: 1, tarOffset: 0, tarSize: 100 }));

      const picked = await service.nextForEvaluation('alice', 'gender', ['indexed']);
      expect(picked?.clipId).toBe('not-indexed');
    });
  });
});
