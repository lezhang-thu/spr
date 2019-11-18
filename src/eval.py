# -*- coding: utf-8 -*-
from __future__ import division
import os
import plotly
import plotly.graph_objects as go
from plotly.graph_objs.scatter import Line
import torch

from src.envs import Env
import wandb

# Test DQN
from src.video_recorder import VideoRecorder


def test(args, T, dqn, model, encoder, metrics, results_dir, evaluate=False):
    env = Env(args)
    env.eval()
    metrics['steps'].append(T)
    T_rewards, T_Qs = [], []

    if args.video:
        video_recorder = VideoRecorder(env, path=os.path.join(wandb.run.dir, args.game + '_' + str(T) + '.mp4'))
        video_recorder.capture_frame()

    # Test performance over several episodes
    done = True
    for _ in range(args.evaluation_episodes):
        while True:
            if done:
                state, reward_sum, done = env.reset(), 0, False

            state = encoder(state).view(-1)
            action = dqn.act_with_planner(state, model,
                                          length=args.planning_horizon,
                                          shots=args.planning_shots)  # Choose an action ε-greedily
            state, reward, done = env.step(action)  # Step
            reward_sum += reward
            if args.render:
                env.render()

            if args.video:
                video_recorder.capture_frame()

            if done:
                T_rewards.append(reward_sum)
                break

    video_recorder.close()
    env.close()

    # # Test Q-values over validation memory
    # for state in val_mem:  # Iterate over valid states
    #   T_Qs.append(dqn.evaluate_q(state))

    avg_reward = sum(T_rewards) / len(T_rewards)
    if not evaluate:
        # Save model parameters if improved
        if avg_reward > metrics['best_avg_reward']:
            metrics['best_avg_reward'] = avg_reward
            dqn.save(results_dir)

        # Append to results and save metrics
        metrics['rewards'].append(T_rewards)
        # metrics['Qs'].append(T_Qs)
        torch.save(metrics, os.path.join(results_dir, 'metrics.pth'))

        # Plot
        _plot_line(metrics['steps'], metrics['rewards'], 'Reward', path=results_dir)
        # _plot_line(metrics['steps'], metrics['Qs'], 'Q', path=results_dir)

    # Return average reward and Q-value
    return avg_reward


# Plots min, max and mean + standard deviation bars of a population over time
def _plot_line(xs, ys_population, title, path=''):
    max_colour, mean_colour, std_colour, transparent = 'rgb(0, 132, 180)', 'rgb(0, 172, 237)', 'rgba(29, 202, 255, 0.2)', 'rgba(0, 0, 0, 0)'

    ys = torch.tensor(ys_population, dtype=torch.float32)
    ys_min, ys_max, ys_mean, ys_std = ys.min(1)[0].squeeze(), ys.max(1)[0].squeeze(), ys.mean(1).squeeze(), ys.std(
        1).squeeze()
    ys_upper, ys_lower = ys_mean + ys_std, ys_mean - ys_std

    trace_max = go.Scatter(x=xs, y=ys_max.numpy(), line=Line(color=max_colour, dash='dash'), name='Max')
    trace_upper = go.Scatter(x=xs, y=ys_upper.numpy(), line=Line(color=transparent), name='+1 Std. Dev.',
                             showlegend=False)
    trace_mean = go.Scatter(x=xs, y=ys_mean.numpy(), fill='tonexty', fillcolor=std_colour, line=Line(color=mean_colour),
                            name='Mean')
    trace_lower = go.Scatter(x=xs, y=ys_lower.numpy(), fill='tonexty', fillcolor=std_colour,
                             line=Line(color=transparent), name='-1 Std. Dev.', showlegend=False)
    trace_min = go.Scatter(x=xs, y=ys_min.numpy(), line=Line(color=max_colour, dash='dash'), name='Min')

    plotly.offline.plot({
        'data': [trace_upper, trace_mean, trace_lower, trace_min, trace_max],
        'layout': dict(title=title, xaxis={'title': 'Step'}, yaxis={'title': title})
    }, filename=os.path.join(path, title + '.html'), auto_open=False)
