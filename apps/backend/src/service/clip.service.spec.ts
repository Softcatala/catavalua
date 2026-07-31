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
});
