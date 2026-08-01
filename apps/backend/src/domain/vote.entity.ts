import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, JoinColumn, Unique, Index } from 'typeorm';
import { Clip } from './clip.entity';

// dimension: 'transcription' | 'gender' | 'dialect' | (any future metadata field)
// For 'transcription' dimension, target_id is the transcription id (as string)
// For other dimensions, target_id is the value being voted on (e.g. 'female')
//
// Uniqueness includes target_id so a user can hold independent votes on competing
// candidates within the same dimension (e.g. -1 on 'female' and +1 on 'male' at once).

@Entity('votes')
@Unique(['clipId', 'dimension', 'targetId', 'username'])
// The existing unique index leads with clipId, so it can't serve lookups
// that start from username or dimension alone — both needed by
// ClipService.nextForEvaluation (exclude-already-voted, dialect signal).
@Index(['username', 'dimension', 'clipId'])
@Index(['dimension', 'clipId'])
export class Vote {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'clip_id' })
  clipId: string;

  @ManyToOne(() => Clip, (c) => c.votes)
  @JoinColumn({ name: 'clip_id' })
  clip: Clip;

  @Column()
  dimension: string;

  @Column({ name: 'target_id', nullable: true })
  targetId: string;

  @Column()
  username: string;

  @Column('integer')
  value: number; // +1 correct, -1 incorrect

  @Column({ name: 'created_at', nullable: true })
  createdAt: string;
}
