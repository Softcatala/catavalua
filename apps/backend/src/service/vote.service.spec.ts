import { Test } from '@nestjs/testing';
import { TypeOrmModule, getRepositoryToken } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { VoteService } from './vote.service';
import { Vote } from '../domain/vote.entity';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';

describe('VoteService', () => {
  let service: VoteService;
  let repo: Repository<Vote>;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      imports: [
        TypeOrmModule.forRoot({
          type: 'sqlite',
          database: ':memory:',
          // Vote's @ManyToOne(Clip) needs the full entity graph registered,
          // otherwise TypeORM's metadata build fails in a way that
          // @nestjs/typeorm's retry logic reports as a misleading
          // "sqlite3 not installed" error.
          entities: [Vote, Clip, Transcription],
          synchronize: true,
        }),
        TypeOrmModule.forFeature([Vote, Clip]),
      ],
      providers: [VoteService],
    }).compile();

    service = module.get(VoteService);
    repo = module.get(getRepositoryToken(Vote));

    // Vote.clipId is a real FK against clips, so seed the clips these tests vote on.
    const clips: Repository<Clip> = module.get(getRepositoryToken(Clip));
    await clips.save(clips.create({ clipId: 'clip-1', gender: 'female' }));
    await clips.save(clips.create({ clipId: 'clip-2', detectedDialect: 'central' }));
  });

  it('lets a user hold independent votes on competing candidates within one dimension', async () => {
    // Downvoting the current gender and upvoting the proposed alternative used to
    // collide on the old (clipId, dimension, username) unique constraint.
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'female', username: 'alice', value: -1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: 1 });

    const rows = await repo.find({ where: { clipId: 'clip-1', username: 'alice' } });
    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.targetId === 'female')?.value).toBe(-1);
    expect(rows.find((r) => r.targetId === 'male')?.value).toBe(1);
  });

  it('upserts in place when the same user votes again on the same target', async () => {
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: 1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: -1 });

    const rows = await repo.find({ where: { clipId: 'clip-1', username: 'alice', targetId: 'male' } });
    expect(rows).toHaveLength(1);
    expect(rows[0].value).toBe(-1);
  });

  it('raises a competing gender candidate to golden once two evaluators confirm it', async () => {
    // dave downvotes the original 'female' label and raises 'male' as the alternative
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'female', username: 'dave', value: -1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'dave', value: 1 });
    // erin independently confirms 'male'
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'erin', value: 1 });

    const summary = await service.summaryForClip('clip-1');
    const male = summary.find((s) => s.targetId === 'male');
    const female = summary.find((s) => s.targetId === 'female');

    expect(male).toMatchObject({ netVotes: 2, isGolden: true });
    expect(female).toMatchObject({ netVotes: -1, isGolden: false });
  });

  it('supports a dialect candidate chosen from a picker the same way', async () => {
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'central', username: 'alice', value: -1 });
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'valencian', username: 'alice', value: 1 });
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'valencian', username: 'bob', value: 1 });

    const summary = await service.summaryForClip('clip-2');
    const valencian = summary.find((s) => s.targetId === 'valencian');

    expect(valencian).toMatchObject({ netVotes: 2, isGolden: true });
  });
});
